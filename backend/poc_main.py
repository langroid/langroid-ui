#!/usr/bin/env python3
"""
Proof of concept for Langroid Web UI with proper callback integration.
This version focuses on method overriding to ensure callbacks are used.
"""
import os
import sys
import asyncio
import logging
import threading
from pathlib import Path
from typing import Optional, Dict, Any
from uuid import uuid4
import queue

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import uvicorn

# Add the parent directory to the path to import langroid
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import langroid as lr
from langroid.agent.chat_agent import ChatAgent, ChatAgentConfig
from langroid.agent.task import Task
from langroid.language_models import MockLMConfig
from langroid.language_models.openai_gpt import OpenAIGPTConfig
from langroid.mytypes import Entity

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(title="Langroid POC Backend", version="poc")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class WebUICallbacks:
    """
    Simplified callback manager that overrides agent methods.
    """
    
    def __init__(self, agent: ChatAgent, websocket: WebSocket):
        self.agent = agent
        self.websocket = websocket
        self.message_queue = asyncio.Queue()
        self.user_input_queue = queue.Queue()
        self.waiting_for_user = False
        
        # Store the main event loop for thread-safe operations
        self._main_loop = asyncio.get_event_loop()
        
        # Store original methods
        self._original_llm_response = agent.llm_response
        self._original_llm_response_async = agent.llm_response_async
        self._original_user_response = agent.user_response
        
        # Override methods
        agent.llm_response = self._llm_response_with_ui
        agent.llm_response_async = self._llm_response_async_with_ui
        agent.user_response = self._user_response_with_ui
        
        # Start message processor
        asyncio.create_task(self._process_messages())
        
        logger.info("WebUICallbacks initialized and methods overridden")
        
    async def _process_messages(self):
        """Process messages from queue and send via WebSocket"""
        while True:
            try:
                message = await self.message_queue.get()
                await self.websocket.send_json(message)
                logger.debug(f"Sent message: {message}")
            except Exception as e:
                logger.error(f"Error sending message: {e}")
                break
                
    def _queue_message(self, message: dict):
        """Queue a message for sending"""
        # Get the event loop from the main thread
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Schedule the coroutine on the main loop
                asyncio.run_coroutine_threadsafe(
                    self.message_queue.put(message), 
                    loop
                )
            else:
                # If no running loop, try to create task
                asyncio.create_task(self.message_queue.put(message))
        except RuntimeError:
            # We're in a thread without an event loop
            # Get the main loop that was stored during init
            if hasattr(self, '_main_loop'):
                asyncio.run_coroutine_threadsafe(
                    self.message_queue.put(message),
                    self._main_loop
                )
        
    def _llm_response_with_ui(self, message=None):
        """Wrapped LLM response that sends to UI"""
        logger.info("_llm_response_with_ui called")
        
        # Call original method
        response = self._original_llm_response(message)
        
        # Send response to UI
        if response and response.content:
            self._queue_message({
                "type": "message",
                "message": {
                    "id": str(uuid4()),
                    "content": response.content,
                    "sender": "assistant"
                }
            })
            
        return response
        
    async def _llm_response_async_with_ui(self, message=None):
        """Async version of LLM response wrapper"""
        logger.info("_llm_response_async_with_ui called")
        
        # Call original method
        response = await self._original_llm_response_async(message)
        
        # Send response to UI
        if response and response.content:
            await self.message_queue.put({
                "type": "message",
                "message": {
                    "id": str(uuid4()),
                    "content": response.content,
                    "sender": "assistant"
                }
            })
            
        return response
        
    def _user_response_with_ui(self, message=None):
        """Wrapped user response that waits for WebSocket input"""
        logger.info("_user_response_with_ui called")
        
        # Send input request to UI
        prompt = "Enter your message:"
        if message and hasattr(message, 'content'):
            prompt = message.content
            
        self._queue_message({
            "type": "input_request",
            "prompt": prompt,
            "request_id": str(uuid4())
        })
        
        # Wait for user input
        self.waiting_for_user = True
        try:
            # Block until we get input
            user_input = self.user_input_queue.get(timeout=300)  # 5 minute timeout
            logger.info(f"Got user input: {user_input}")
            
            # Return as ChatDocument
            return lr.ChatDocument(
                content=user_input,
                metadata=lr.ChatDocMetaData(sender=Entity.USER)
            )
        except queue.Empty:
            logger.error("User input timeout")
            return None
        finally:
            self.waiting_for_user = False
            
    def handle_user_message(self, content: str):
        """Called when user sends a message via WebSocket"""
        logger.info(f"handle_user_message: {content}")
        if self.waiting_for_user:
            self.user_input_queue.put(content)


class POCSession:
    """Simplified session management"""
    
    def __init__(self, session_id: str, websocket: WebSocket):
        self.session_id = session_id
        self.websocket = websocket
        self.agent = self._create_agent()
        self.callbacks = WebUICallbacks(self.agent, websocket)
        self.task = None
        self.task_thread = None
        
    def _create_agent(self) -> ChatAgent:
        """Create agent with MockLM"""
        config = ChatAgentConfig(
            llm=MockLMConfig(
                response_dict={
                    "hello": "Hello! I'm a Langroid agent with working callbacks!",
                    "test": "The callbacks are working! I can see your messages.",
                    "default": "I'm responding through the WebSocket connection!"
                }
            ),
            name="POCAgent",
            system_message="You are a test agent for the POC."
        )
        return ChatAgent(config)
        
    def start_conversation(self):
        """Start the conversation loop"""
        logger.info("Starting conversation")
        
        # Create task
        self.task = Task(
            self.agent,
            name="POCTask",
            interactive=True  # This makes it wait for user input
        )
        
        # Run task in thread
        def run_task():
            try:
                logger.info("Task.run() starting")
                result = self.task.run()
                logger.info(f"Task.run() completed: {result}")
            except Exception as e:
                logger.error(f"Task error: {e}")
                import traceback
                traceback.print_exc()
                
        self.task_thread = threading.Thread(target=run_task)
        self.task_thread.start()
        
    def handle_message(self, content: str):
        """Handle incoming user message"""
        logger.info(f"Session handling message: {content}")
        self.callbacks.handle_user_message(content)
        
    def stop(self):
        """Stop the session"""
        if self.task:
            self.task.done = True
        if self.task_thread:
            self.task_thread.join(timeout=5)


# Global session storage
sessions: Dict[str, POCSession] = {}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint"""
    await websocket.accept()
    session_id = f"poc_{uuid4().hex[:8]}"
    
    try:
        # Create session
        session = POCSession(session_id, websocket)
        sessions[session_id] = session
        
        # Send connection message
        await websocket.send_json({
            "type": "connection",
            "session_id": session_id,
            "message": "Connected to POC backend"
        })
        
        # Start conversation
        session.start_conversation()
        
        # Handle messages
        while True:
            data = await websocket.receive_json()
            logger.info(f"Received: {data}")
            
            if data.get("type") == "message":
                content = data.get("content", "")
                session.handle_message(content)
                
    except WebSocketDisconnect:
        logger.info(f"Session {session_id} disconnected")
    except Exception as e:
        logger.error(f"Session {session_id} error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Cleanup
        if session_id in sessions:
            sessions[session_id].stop()
            del sessions[session_id]
        try:
            await websocket.close()
        except:
            pass


if __name__ == "__main__":
    uvicorn.run(
        "poc_main:app",
        host="0.0.0.0",
        port=8001,  # Different port to avoid conflict
        reload=True
    )
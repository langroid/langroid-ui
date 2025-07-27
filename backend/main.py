import os
import sys
from pathlib import Path
import asyncio
from typing import Dict, Optional
from datetime import datetime
import json
from queue import Queue, Empty
import threading

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

# Add the parent directory to the path to import langroid
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import langroid as lr
from langroid.language_models import MockLMConfig
from langroid.agent.chat_agent import ChatAgent, ChatAgentConfig
from langroid.agent.task import Task, TaskConfig
from langroid.language_models.openai_gpt import OpenAIGPTConfig
from langroid.utils.constants import DONE


class UIChatAgent(ChatAgent):
    """Custom ChatAgent that reads from a queue instead of stdin"""
    def __init__(self, config: ChatAgentConfig, input_queue: Queue[str], running_flag):
        super().__init__(config)
        self.input_queue = input_queue
        self.running_flag = running_flag
    
    def user_response(self, msg: Optional[str] = None) -> Optional[lr.ChatDocument]:
        """Override to read from queue instead of stdin"""
        # Display the agent's message if provided
        if msg:
            print(f"Agent says: {msg}")
        
        # Wait for user input from the queue
        while self.running_flag():
            try:
                # Block waiting for input with timeout
                user_input = self.input_queue.get(timeout=0.5)
                
                if user_input.lower() in ['quit', 'exit', 'q', 'x']:
                    return lr.ChatDocument(
                        content=DONE,
                        metadata=lr.ChatDocMetaData(
                            sender=lr.Entity.USER,
                        )
                    )
                
                # Return the user input as a ChatDocument
                return self.create_user_response(user_input)
                
            except Empty:
                continue
            except Exception as e:
                print(f"Error in user_response: {e}")
                return None
        
        # If not running, return DONE
        return lr.ChatDocument(
            content=DONE,
            metadata=lr.ChatDocMetaData(
                sender=lr.Entity.USER,
            )
        )


class Message(BaseModel):
    id: str
    content: str
    sender: str
    timestamp: datetime


class ChatSession:
    """Manages a single chat session with its own agent and task"""
    def __init__(self, session_id: str, websocket: WebSocket):
        self.session_id = session_id
        self.websocket = websocket
        self.input_queue: Queue[str] = Queue()
        self.running = False
        self.task_thread: Optional[threading.Thread] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        
        # Create agent with custom user_response
        self.agent = self._create_agent()
        self.task_config = TaskConfig(
            addressing_prefix="",
        )
        self.task = Task(self.agent, interactive=True, config=self.task_config)
        
    def _create_agent(self) -> UIChatAgent:
        """Create agent with appropriate LLM config"""
        # Check if we should force mock mode
        use_mock = os.getenv("USE_MOCK_LLM", "").lower() in ["true", "1", "yes"]
        openai_key = os.getenv("OPENAI_API_KEY")
        
        # Use mock if explicitly requested OR if no API key is present
        if use_mock or not openai_key:
            print("🤖 Using MockLM - no API keys required!")
            config = ChatAgentConfig(
                llm=MockLMConfig(
                    response_dict={
                        "hello": "Hello! I'm a mock Langroid agent running locally without any API keys. How can I help you test the chat interface?",
                        "hi": "Hi there! I'm the mock assistant. Try asking me to calculate something, or ask about the weather!",
                        "help": "I can help you test the chat UI! Try these:\n- Basic math (e.g., 'What is 5 + 7?')\n- Weather queries\n- General conversation\n- Or just chat about anything!",
                        "weather": "I'm a mock model, so I can't check real weather, but let's pretend it's sunny with a chance of debugging! ☀️",
                        "coding": "I love talking about code! This UI is built with React and FastAPI. What would you like to know?",
                        "math|calculate|what is": "Let me pretend to calculate that for you... The answer is 42! (I'm a mock, so I always give the same answer 😄)",
                        "5 + 7|5+7": "5 + 7 equals 12! (Even a mock can do simple math sometimes)",
                        "bye|goodbye": "Goodbye! Thanks for testing the Langroid Chat UI!",
                        "langroid": "Langroid is an amazing framework for building LLM-powered applications! This chat UI demonstrates how to integrate it with web technologies.",
                        "test": "Testing, testing, 1-2-3! The WebSocket connection seems to be working well!",
                        "default": "That's interesting! As a mock agent, I have limited responses, but I'm here to help test the chat interface. What else would you like to try?",
                    },
                    default_response="I'm a mock Langroid agent with limited responses. Try asking about math, weather, or just say hello!"
                ),
                system_message="You are a mock assistant for testing the Langroid Chat UI without API keys."
            )
        else:
            print(f"🔑 Using OpenAI GPT (API key: {openai_key[:8]}...)")
            config = ChatAgentConfig(
                llm=OpenAIGPTConfig(
                    chat_model="gpt-4o-mini",
                    chat_context_length=16000,
                ),
                system_message="""You are a helpful AI assistant in a chat interface. 
                Be concise and friendly in your responses. Remember our conversation history."""
            )
        
        # Return our custom agent with queue-based input
        return UIChatAgent(config, self.input_queue, lambda: self.running)
    
    
    def _run_task_loop(self):
        """Run the task loop in a separate thread"""
        try:
            # Run the task - this will loop between user_response and llm_response
            # In interactive mode, it will automatically wait for user input
            self.task.run()
            
        except Exception as e:
            print(f"Task error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self.running = False
    
    async def start(self, loop: asyncio.AbstractEventLoop):
        """Start the chat session"""
        self.loop = loop
        self.running = True
        
        # Start the task in a separate thread
        self.task_thread = threading.Thread(target=self._run_task_loop)
        self.task_thread.start()
        
        # Start monitoring for agent responses
        asyncio.create_task(self._monitor_responses())
    
    async def send_user_message(self, content: str):
        """Send a user message to the agent"""
        # Put the message in the queue for the custom user_response to pick up
        self.input_queue.put(content)
    
    async def _monitor_responses(self):
        """Monitor the agent's message history and send new messages to the frontend"""
        last_index = 0
        
        while self.running:
            try:
                # Check for new messages in the agent's history
                history = self.agent.message_history
                
                if len(history) > last_index:
                    # Process new messages
                    for i in range(last_index, len(history)):
                        msg = history[i]
                        
                        # Only send LLM/ASSISTANT messages to frontend
                        if hasattr(msg, 'metadata') and msg.metadata:
                            sender = msg.metadata.sender
                            if sender in [lr.Entity.LLM, lr.Entity.ASSISTANT]:
                                # Send to frontend
                                data = {
                                    "type": "message",
                                    "message": {
                                        "id": f"{datetime.now().timestamp()}",
                                        "content": msg.content,
                                        "sender": "assistant",
                                        "timestamp": datetime.now().isoformat(),
                                    }
                                }
                                await self._send_to_frontend(data)
                    
                    last_index = len(history)
                
                await asyncio.sleep(0.1)
                
            except Exception as e:
                print(f"Monitor error: {e}")
                import traceback
                traceback.print_exc()
                break
    
    async def _send_to_frontend(self, data: dict):
        """Send data to frontend via WebSocket"""
        if self.loop and self.websocket:
            try:
                await self.websocket.send_json(data)
            except Exception as e:
                print(f"Error sending to frontend: {e}")
    
    def stop(self):
        """Stop the chat session"""
        self.running = False
        # Send quit to unblock user_response
        self.input_queue.put("quit")
        
        if self.task_thread:
            self.task_thread.join(timeout=5)


class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.sessions: Dict[str, ChatSession] = {}

    async def connect(self, websocket: WebSocket, session_id: str):
        await websocket.accept()
        self.active_connections[session_id] = websocket
        
        # Create new chat session
        session = ChatSession(session_id, websocket)
        self.sessions[session_id] = session
        
        # Start the session
        await session.start(asyncio.get_event_loop())

    def disconnect(self, session_id: str):
        if session_id in self.active_connections:
            del self.active_connections[session_id]
            
        if session_id in self.sessions:
            self.sessions[session_id].stop()
            del self.sessions[session_id]


app = FastAPI()

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

manager = ConnectionManager()


@app.get("/")
async def root():
    return {"message": "Langroid Chat API", "status": "running"}


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    session_id = f"session_{id(websocket)}"
    
    await manager.connect(websocket, session_id)
    
    try:
        while True:
            # Receive message from client
            data = await websocket.receive_json()
            
            if data.get("type") == "message":
                user_content = data.get("content", "")
                
                # Get session
                session = manager.sessions.get(session_id)
                if session:
                    # Send user message to agent
                    await session.send_user_message(user_content)
                    
    except WebSocketDisconnect:
        manager.disconnect(session_id)


if __name__ == "__main__":
    import argparse
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Langroid Chat UI Backend")
    parser.add_argument("--mock", action="store_true", help="Force use of MockLM even if API keys are present")
    parser.add_argument("--port", type=int, default=8000, help="Port to run the server on (default: 8000)")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind the server to (default: 0.0.0.0)")
    args = parser.parse_args()
    
    # Load environment variables
    from dotenv import load_dotenv
    load_dotenv()
    
    # Override USE_MOCK_LLM if --mock flag is used
    if args.mock:
        os.environ["USE_MOCK_LLM"] = "true"
        print("🎭 Mock mode enabled via CLI flag")
    
    # Run the server
    uvicorn.run(
        "main:app",
        host=args.host,
        port=args.port,
        reload=True,
        ws_ping_interval=30,
        ws_ping_timeout=30,
    )
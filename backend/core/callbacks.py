"""
WebUI callbacks using method overriding approach.
Based on the proven POC implementation.
"""
import asyncio
import logging
import queue
from typing import Optional
from uuid import uuid4

from fastapi import WebSocket

import langroid as lr
from langroid.mytypes import Entity

from models.messages import ChatMessage, CompleteMessage, InputRequest
from utils.async_bridge import queue_message_threadsafe

logger = logging.getLogger(__name__)


class WebUICallbacks:
    """
    Callback manager that overrides agent methods to integrate with WebSocket UI.
    
    This approach ensures callbacks are always used by overriding the agent's
    core response methods rather than relying on optional callback hooks.
    """
    
    def __init__(self, agent: lr.ChatAgent, websocket: WebSocket):
        self.agent = agent
        self.websocket = websocket
        
        # Message queues
        self.outgoing_queue = asyncio.Queue()  # Messages to WebSocket
        self.user_input_queue = queue.Queue()  # User input from WebSocket
        
        # State
        self.waiting_for_user = False
        self.current_message_id: Optional[str] = None
        
        # Store the main event loop for thread-safe operations
        self._main_loop = asyncio.get_event_loop()
        
        # Store original methods before overriding
        self._original_llm_response = agent.llm_response
        self._original_llm_response_async = agent.llm_response_async
        self._original_user_response = agent.user_response
        
        # Override agent methods
        self._override_methods()
        
        # Start message processor
        asyncio.create_task(self._process_outgoing_messages())
        
        logger.info(f"WebUICallbacks initialized for agent {agent.config.name}")
        
    def _override_methods(self):
        """Override agent methods to intercept responses."""
        self.agent.llm_response = self._llm_response_with_ui
        self.agent.llm_response_async = self._llm_response_async_with_ui
        self.agent.user_response = self._user_response_with_ui
        
    async def _process_outgoing_messages(self):
        """Process messages from queue and send via WebSocket."""
        while True:
            try:
                message = await self.outgoing_queue.get()
                await self.websocket.send_json(message)
                logger.debug(f"Sent message type: {message.get('type')}")
            except Exception as e:
                logger.error(f"Error sending message: {e}")
                break
                
    def _queue_message(self, message: dict):
        """Queue a message for sending via WebSocket."""
        queue_message_threadsafe(message, self.outgoing_queue, self._main_loop)
        
    def _llm_response_with_ui(self, message=None):
        """Wrapped LLM response that sends to UI."""
        logger.info("LLM response requested")
        
        # Call original method
        response = self._original_llm_response(message)
        
        # Send response to UI if we got one
        if response and response.content:
            self._send_assistant_message(response.content)
            
        return response
        
    async def _llm_response_async_with_ui(self, message=None):
        """Async version of LLM response wrapper."""
        logger.info("Async LLM response requested")
        
        # Call original method
        response = await self._original_llm_response_async(message)
        
        # Send response to UI if we got one
        if response and response.content:
            self._send_assistant_message(response.content)
            
        return response
        
    def _user_response_with_ui(self, message=None):
        """Wrapped user response that waits for WebSocket input."""
        logger.info("User response requested")
        
        # Determine prompt
        prompt = "Enter your message:"
        if message and hasattr(message, 'content'):
            prompt = message.content
            
        # Send input request to UI
        request_id = str(uuid4())
        self._queue_message({
            "type": "input_request",
            "prompt": prompt,
            "request_id": request_id
        })
        
        # Wait for user input
        self.waiting_for_user = True
        try:
            # Block until we get input (5 minute timeout)
            user_input = self.user_input_queue.get(timeout=300)
            logger.info(f"Received user input: {user_input[:50]}...")
            
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
            
    def _send_assistant_message(self, content: str):
        """Send an assistant message to the UI."""
        message = CompleteMessage(
            message=ChatMessage(
                id=str(uuid4()),
                content=content,
                sender="assistant"
            )
        )
        self._queue_message(message.dict())
        
    def handle_user_message(self, content: str):
        """
        Called when user sends a message via WebSocket.
        If we're waiting for input, queue it for the waiting method.
        """
        logger.info(f"Handling user message: {content[:50]}...")
        
        if self.waiting_for_user:
            self.user_input_queue.put(content)
        else:
            logger.warning("Received user message but not waiting for input")
            
    async def send_system_message(self, content: str):
        """Send a system message to the UI."""
        message = CompleteMessage(
            message=ChatMessage(
                id=str(uuid4()),
                content=content,
                sender="system"
            )
        )
        await self.outgoing_queue.put(message.dict())
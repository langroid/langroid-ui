"""
WebUI callbacks using method overriding approach.
Based on the proven POC implementation.
"""
import asyncio
import hashlib
import logging
import queue
from typing import Optional
from uuid import uuid4

from fastapi import WebSocket

import langroid as lr
from langroid.mytypes import Entity

from models.messages import (
    ChatMessage, CompleteMessage, InputRequest,
    StreamStart, StreamToken, StreamEnd
)
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
        self.current_stream_id: Optional[str] = None
        self.stream_started = False  # Track if streaming was initiated
        self.stream_buffer = []
        self.streamed_message_ids = set()  # Track which messages were streamed
        self.cached_message_sent = False  # Track if cached message was already sent
        
        # Store the main event loop for thread-safe operations
        try:
            self._main_loop = asyncio.get_running_loop()
            logger.info(f"🔄 Stored running event loop: {id(self._main_loop)}")
        except RuntimeError:
            # If no running loop, try to get the current one
            self._main_loop = asyncio.get_event_loop()
            logger.info(f"🔄 Stored current event loop: {id(self._main_loop)}")
            logger.warning("⚠️ No running loop when initializing callbacks")
        
        # Store original methods before overriding
        self._original_llm_response = agent.llm_response
        self._original_llm_response_async = agent.llm_response_async
        self._original_user_response = agent.user_response
        
        # Override agent methods
        self._override_methods()
        
        # Inject streaming callbacks
        self._inject_streaming_callbacks()
        
        # Start message processor - this will be started by the session manager
        self._processor_task = None
        
        logger.info(f"WebUICallbacks initialized for agent {agent.config.name}")
        
    async def start_processor(self):
        """Start the message processor coroutine."""
        if self._processor_task is None:
            logger.info("🚀 Starting message processor task")
            self._processor_task = asyncio.create_task(self._process_outgoing_messages())
            logger.info(f"🚀 Message processor task created: {self._processor_task}")
        else:
            logger.warning("⚠️ Message processor already running")
        
    def _override_methods(self):
        """Override agent methods to intercept responses."""
        # Store original methods
        self._original_llm_response = self.agent.llm_response
        self._original_llm_response_async = self.agent.llm_response_async
        self._original_user_response = self.agent.user_response
        
        # Override main methods
        self.agent.llm_response = self._llm_response_with_ui
        self.agent.llm_response_async = self._llm_response_async_with_ui
        self.agent.user_response = self._user_response_with_ui
        
        # ALSO override the methods that Tasks might actually call
        if hasattr(self.agent, 'llm_response_messages'):
            self._original_llm_response_messages = self.agent.llm_response_messages
            self.agent.llm_response_messages = self._llm_response_messages_with_ui
            
        if hasattr(self.agent, 'llm_response_messages_async'):
            self._original_llm_response_messages_async = self.agent.llm_response_messages_async
            self.agent.llm_response_messages_async = self._llm_response_messages_async_with_ui
            
        if hasattr(self.agent, 'agent_response'):
            self._original_agent_response = self.agent.agent_response
            self.agent.agent_response = self._agent_response_with_ui
        
    def _inject_streaming_callbacks(self):
        """Inject streaming callbacks into the agent."""
        # Ensure agent has callbacks object
        if not hasattr(self.agent, 'callbacks'):
            from types import SimpleNamespace
            self.agent.callbacks = SimpleNamespace()
            
        # Set streaming callbacks
        self.agent.callbacks.start_llm_stream = self.start_llm_stream
        self.agent.callbacks.start_llm_stream_async = self.start_llm_stream_async
        self.agent.callbacks.finish_llm_stream = self.finish_llm_stream
        
        # Override show_llm_response to prevent duplicates
        # This is called by Langroid after getting the LLM response
        self.agent.callbacks.show_llm_response = self._show_llm_response_override
        
        logger.info("Streaming callbacks injected")
        
    async def _process_outgoing_messages(self):
        """Process messages from queue and send via WebSocket."""
        logger.debug("Starting _process_outgoing_messages coroutine")
        while True:
            try:
                message = await self.outgoing_queue.get()
                logger.debug(f"Sending message: type={message.get('type')}")
                
                await self.websocket.send_json(message)
                
                # Mark the task as done
                self.outgoing_queue.task_done()
                
            except Exception as e:
                logger.error(f"❌ Error in _process_outgoing_messages: {e}")
                import traceback
                traceback.print_exc()
                break
        logger.error("_process_outgoing_messages coroutine ended")
                
    def _queue_message(self, message: dict):
        """Queue a message for sending via WebSocket."""
        queue_message_threadsafe(message, self.outgoing_queue, self._main_loop)
        
    def _llm_response_with_ui(self, message=None):
        """Wrapped LLM response that sends to UI."""
        logger.info("SYNC LLM response requested")
        
        # Reset cached message flag at the start of a new response cycle
        self.cached_message_sent = False
        
        # Track if streaming was used for this response
        # Check if streaming was started for this response
        was_streamed = self.stream_started
        
        # Reset the flag for next response
        self.stream_started = False
        
        # Call original method
        response = self._original_llm_response(message)
        
        # Don't send anything from this method - let llm_response_messages handle it
        logger.info("SYNC: llm_response completed, not sending message here")
            
        return response
        
    async def _llm_response_async_with_ui(self, message=None):
        """Async version of LLM response wrapper."""
        logger.info("ASYNC LLM response requested")
        
        # Track if streaming was used for this response
        # Check if streaming was started for this response
        was_streamed = self.stream_started
        
        # Reset the flag for next response
        self.stream_started = False
        
        # Call original method
        response = await self._original_llm_response_async(message)
        
        # Only send complete message if it's cached (cached responses don't stream)
        if response and response.content:
            is_cached = hasattr(response, 'metadata') and getattr(response.metadata, 'cached', False)
            if is_cached:
                self._send_assistant_message(response.content)
                logger.info(f"ASYNC: Sent complete message for cached response")
            else:
                logger.info(f"ASYNC: Skipped complete message - will be streamed")
            
        return response
        
    def _llm_response_messages_with_ui(self, *args, **kwargs):
        """Wrapped llm_response_messages that sends to UI."""
        # Call original method with all arguments
        response = self._original_llm_response_messages(*args, **kwargs)
        
        # This is the primary method for sending cached messages
        if response and hasattr(response, 'content') and response.content:
            is_cached = hasattr(response, 'metadata') and getattr(response.metadata, 'cached', False)
            if is_cached and not self.cached_message_sent:
                self._send_assistant_message(response.content)
                self.cached_message_sent = True
                logger.debug("PRIMARY: Sent complete message for cached response")
            elif is_cached:
                logger.debug("PRIMARY: Skipped cached message - already sent")
            else:
                logger.debug("PRIMARY: Skipping complete message - will be streamed")
            
        return response
        
    async def _llm_response_messages_async_with_ui(self, *args, **kwargs):
        """Async wrapped llm_response_messages that sends to UI."""
        # Call original method with all arguments
        response = await self._original_llm_response_messages_async(*args, **kwargs)
        
        # Only send complete message if it's cached (cached responses don't stream)
        if response and hasattr(response, 'content') and response.content:
            is_cached = hasattr(response, 'metadata') and getattr(response.metadata, 'cached', False)
            if is_cached:
                self._send_assistant_message(response.content)
                logger.debug("Sent complete message for cached response")
            else:
                logger.debug("Skipping complete message - will be streamed")
            
        return response
        
    def _agent_response_with_ui(self, message=None):
        """Wrapped agent_response that sends to UI."""
        
        # Call original method
        response = self._original_agent_response(message)
        
        # Don't send anything - let llm_response_messages handle all messages
        if response and hasattr(response, 'content') and response.content:
            logger.debug(f"agent_response completed, not sending message here")
            
        return response
        
    def _user_response_with_ui(self, message=None):
        """Wrapped user response that waits for WebSocket input."""
        logger.info("User response requested")
        
        # We don't need to send an input_request message to the UI
        # The frontend already has a persistent input field
        # Just wait for user input
        
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
        # Don't send empty messages
        if not content or not content.strip():
            logger.warning("Skipping empty assistant message")
            return
            
        msg_id = str(uuid4())
        
        message = CompleteMessage(
            message=ChatMessage(
                id=msg_id,
                content=content,
                sender="assistant"
            )
        )
        self._queue_message(message.dict())
        
    def handle_user_message(self, content: str):
        """
        Called when user sends a message via WebSocket.
        Always queue the message - the waiting method will consume it.
        """
        # Always queue the message - don't check waiting_for_user flag
        # This ensures messages aren't lost if they arrive before _user_response_with_ui is called
        self.user_input_queue.put(content)
        logger.debug(f"User message queued: {content[:50]}...")
            
    def _show_llm_response_override(self, content: str, is_tool: bool = False, cached: bool = False, language: str = None):
        """
        Override of Langroid's show_llm_response callback.
        We handle message sending in our _llm_response_with_ui method,
        so this is a no-op to prevent duplicates.
        """
        # Do nothing - we handle message sending in _llm_response_with_ui
        pass
            
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
        
    # Streaming support methods
    
    def start_llm_stream(self):
        """
        Called when LLM starts streaming. Returns a function that handles tokens.
        """
        # Create a new message ID for this stream
        self.current_stream_id = str(uuid4())
        self.stream_started = True  # Mark that streaming has started
        self.stream_buffer = []
        
        # Track that this message ID is being streamed
        self.streamed_message_ids.add(self.current_stream_id)
        
        # Send stream start message
        message = StreamStart(
            message_id=self.current_stream_id,
            sender="assistant"
        )
        self._queue_message(message.dict())
        
        logger.info(f"Started LLM stream: {self.current_stream_id}")
        
        # Return the token handler function
        def stream_token(token: str, event_type=None):
            """Handle a single streaming token."""
            self.stream_buffer.append(token)
            
            # Send token to frontend
            token_msg = StreamToken(
                message_id=self.current_stream_id,
                token=token
            )
            self._queue_message(token_msg.dict())
            
        return stream_token
        
    async def start_llm_stream_async(self):
        """
        Async version of start_llm_stream for async LLM calls.
        """
        # Create a new message ID for this stream
        self.current_stream_id = str(uuid4())
        self.stream_started = True  # Mark that streaming has started
        self.stream_buffer = []
        
        # Send stream start message
        message = StreamStart(
            message_id=self.current_stream_id,
            sender="assistant"
        )
        await self.outgoing_queue.put(message.dict())
        
        logger.info(f"Started async LLM stream: {self.current_stream_id}")
        
        # Return the async token handler function
        async def stream_token(token: str, event_type=None):
            """Handle a single streaming token asynchronously."""
            self.stream_buffer.append(token)
            
            # Send token to frontend
            token_msg = StreamToken(
                message_id=self.current_stream_id,
                token=token
            )
            await self.outgoing_queue.put(token_msg.dict())
            
        return stream_token
        
    def finish_llm_stream(self, content: str = "", is_tool: bool = False):
        """
        Called when LLM finishes streaming.
        
        Args:
            content: The complete response content
            is_tool: Whether this is a tool response
        """
        if self.current_stream_id:
            # Check if any tokens were actually streamed
            if not self.stream_buffer:
                # No tokens were streamed - this was likely a cached response
                # Send a delete message to remove the empty bubble
                logger.info(f"No tokens streamed for {self.current_stream_id} - removing empty message")
                delete_msg = {
                    "type": "delete_message",
                    "message_id": self.current_stream_id
                }
                self._queue_message(delete_msg)
            else:
                # Normal stream end - tokens were streamed
                end_msg = StreamEnd(
                    message_id=self.current_stream_id
                )
                self._queue_message(end_msg.dict())
                logger.info(f"Finished LLM stream: {self.current_stream_id}")
            
            # Note: We don't send the complete message here because
            # our _llm_response_with_ui will handle that
            
            # Clear stream state
            self.current_stream_id = None
            self.stream_buffer = []
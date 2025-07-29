"""
WebSocket callbacks for Langroid UI integration.

This implementation uses Langroid's native callback system while addressing
the limitations discovered during analysis. It provides a hybrid approach
that maximizes use of callbacks while falling back to method overrides
only where necessary.
"""
import asyncio
import json
import logging
import queue
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Union
from types import SimpleNamespace
from uuid import uuid4

from langroid.agent.chat_agent import ChatAgent
from langroid.agent.chat_document import ChatDocument, ChatDocMetaData
from langroid.mytypes import Entity

# Import message models from backend
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))
from models.messages import (
    CompleteMessage, ChatMessage, StreamStart, StreamToken, StreamEnd
)

logger = logging.getLogger(__name__)


@dataclass
class CallbackContext:
    """Context object passed to callbacks for state management."""
    session_id: str
    websocket: Any  # Avoid circular import
    message_queue: asyncio.Queue
    user_input_queue: queue.Queue
    event_loop: asyncio.AbstractEventLoop
    metadata: Dict[str, Any] = field(default_factory=dict)
    current_message_id: Optional[str] = None
    current_stream_id: Optional[str] = None
    



class WebSocketCallbacks:
    """
    WebSocket callback implementation that maximizes use of Langroid's native
    callback system while providing robust UI integration.
    
    This class:
    1. Uses native callbacks for all operations where they exist
    2. Provides enhanced context management for callbacks
    3. Only overrides methods where callbacks are insufficient
    4. Handles sync/async bridging for WebSocket communication
    """
    
    def __init__(self, context: CallbackContext):
        self.context = context
        self._lock = threading.Lock()
        self._streaming_tokens = []
        self._stream_started = False
        self._last_response_was_cached = False
        self._cached_message_sent = False
        
        # Track which methods we've overridden
        self._overridden_methods = set()
        
        logger.info(f"WebSocketCallbacks initialized for session {context.session_id}")
        
    def attach_to_agent(self, agent: ChatAgent):
        """Attach callbacks to a Langroid agent."""
        # Ensure agent has callbacks namespace
        if not hasattr(agent, 'callbacks'):
            from types import SimpleNamespace
            agent.callbacks = SimpleNamespace()
            
        # Attach ALL callbacks directly here
        # Streaming callbacks
        agent.callbacks.start_llm_stream = self.start_llm_stream
        agent.callbacks.start_llm_stream_async = self.start_llm_stream_async
        agent.callbacks.finish_llm_stream = self.finish_llm_stream
        agent.callbacks.cancel_llm_stream = self.cancel_llm_stream
        
        # Display callbacks
        agent.callbacks.show_llm_response = self.show_llm_response
        agent.callbacks.show_agent_response = self.show_agent_response
        agent.callbacks.show_error_message = self.show_error_message
        agent.callbacks.show_start_response = self.show_start_response
        
        # Input callbacks
        agent.callbacks.get_user_response = self.get_user_response
        agent.callbacks.get_user_response_async = self.get_user_response_async
        
        # Apply minimal method overrides only where callbacks don't exist
        self._apply_essential_overrides(agent)
        
        logger.info(f"Callbacks attached to agent {agent.config.name}")
        
        
    def _apply_essential_overrides(self, agent: ChatAgent):
        """
        Apply method overrides to ensure callbacks are triggered.
        
        We need to override multiple methods because Langroid may call
        different ones depending on the context (sync/async, messages/direct).
        """
        # Override llm_response (sync)
        if hasattr(agent, 'llm_response'):
            agent._original_llm_response = agent.llm_response
            agent.llm_response = lambda *args, **kwargs: self._llm_response_with_context(
                agent, *args, **kwargs
            )
            self._overridden_methods.add('llm_response')
            
        # Override llm_response_async
        if hasattr(agent, 'llm_response_async'):
            agent._original_llm_response_async = agent.llm_response_async
            agent.llm_response_async = lambda *args, **kwargs: self._llm_response_async_with_context(
                agent, *args, **kwargs
            )
            self._overridden_methods.add('llm_response_async')
            
        # Override user_response
        if hasattr(agent, 'user_response'):
            agent._original_user_response = agent.user_response
            agent.user_response = lambda *args, **kwargs: self._user_response_with_context(
                agent, *args, **kwargs
            )
            self._overridden_methods.add('user_response')
            
        # Override llm_response_messages
        if hasattr(agent, 'llm_response_messages'):
            agent._original_llm_response_messages = agent.llm_response_messages
            agent.llm_response_messages = lambda *args, **kwargs: self._llm_response_messages_with_context(
                agent, *args, **kwargs
            )
            self._overridden_methods.add('llm_response_messages')
            
        # Override llm_response_messages_async
        if hasattr(agent, 'llm_response_messages_async'):
            agent._original_llm_response_messages_async = agent.llm_response_messages_async
            agent.llm_response_messages_async = lambda *args, **kwargs: self._llm_response_messages_async_with_context(
                agent, *args, **kwargs
            )
            self._overridden_methods.add('llm_response_messages_async')
            
        # Override agent_response
        if hasattr(agent, 'agent_response'):
            agent._original_agent_response = agent.agent_response
            agent.agent_response = lambda *args, **kwargs: self._agent_response_with_context(
                agent, *args, **kwargs
            )
            self._overridden_methods.add('agent_response')
            
        logger.info(f"Applied essential overrides: {self._overridden_methods}")
        
    # Streaming Callbacks
    
    def start_llm_stream(self, **kwargs) -> Callable[[str], None]:
        """Start streaming callback - sync version."""
        self._stream_started = True
        self._streaming_tokens = []
        message_id = str(uuid4())
        self.context.current_stream_id = message_id
        
        # Send stream start message
        stream_start = StreamStart(
            message_id=message_id,
            sender="assistant"
        )
        self._queue_message(stream_start.dict())
        
        def stream_token(token: str, event_type=None) -> None:
            """Handle individual stream token."""
            self._streaming_tokens.append(token)
            token_msg = StreamToken(
                message_id=message_id,
                token=token
            )
            self._queue_message(token_msg.dict())
            
        return stream_token
        
    async def start_llm_stream_async(self, **kwargs) -> Callable[[str], None]:
        """Start streaming callback - async version."""
        # Reuse sync version as the token handler is sync anyway
        return self.start_llm_stream(**kwargs)
        
    def finish_llm_stream(self, content: str, **kwargs) -> None:
        """Finish streaming and send complete message."""
        if not self._stream_started:
            return
            
        message_id = self.context.current_stream_id
        
        # Send stream end
        stream_end = StreamEnd(message_id=message_id)
        self._queue_message(stream_end.dict())
        
        # Send complete message
        complete_msg = CompleteMessage(
            message=ChatMessage(
                id=message_id,
                content=content,
                sender="assistant"
            )
        )
        self._queue_message(complete_msg.dict())
        
        self._stream_started = False
        self.context.current_stream_id = None
        
    def cancel_llm_stream(self) -> None:
        """Cancel streaming (e.g., when cached response found)."""
        if self._stream_started:
            # For now, just send stream end
            stream_end = StreamEnd(message_id=self.context.current_stream_id)
            self._queue_message(stream_end.dict())
            self._stream_started = False
            
    # Display Callbacks
    
    def show_llm_response(self, content: str, is_tool: bool = False, cached: bool = False, **kwargs) -> None:
        """Show LLM response - called for non-streaming responses."""
        logger.info(f"🎯 show_llm_response CALLED! content={content[:50] if content else 'None'}")
        # Do nothing - we handle message sending in our method overrides
        # This prevents duplicate messages
        pass
        
    def show_agent_response(self, content: str, language: str = None, **kwargs) -> None:
        """Show agent response (tool results, etc)."""
        logger.info(f"🎯 show_agent_response CALLED! content={content[:50] if content else 'None'}")
        # Do nothing - we handle message sending in our method overrides
        # This prevents duplicate messages
        pass
        
    def show_error_message(self, error: str) -> None:
        """Show error message."""
        # Send as system message
        message = CompleteMessage(
            message=ChatMessage(
                id=str(uuid4()),
                content=f"Error: {error}",
                sender="system"
            )
        )
        self._queue_message(message.dict())
        
    def show_start_response(self, message: str = "Thinking...") -> None:
        """Show loading/thinking indicator."""
        # For now, we don't send status messages to avoid UI clutter
        # The React frontend shows typing indicators already
        logger.debug(f"Status: {message}")
        
    # Input Callbacks
    
    def get_user_response(self, prompt: str = None) -> str:
        """Get user response - sync version."""
        # Don't send input_request - React frontend already has input field
        # Just wait for user input
        
        logger.info(f"🔵 get_user_response CALLED! prompt: {prompt}")
        logger.info(f"🔵 Queue object: {id(self.context.user_input_queue)}")
        
        # Wait for user input
        try:
            logger.info("🔵 About to wait on queue.get()...")
            user_input = self.context.user_input_queue.get(timeout=300)  # 5 min timeout
            logger.info(f"🟢 Received user input: {user_input[:50]}...")
            
            # Don't echo user message - frontend already displays it
            
            # Return just the string content
            return user_input
        except queue.Empty:
            logger.error("🔴 User input timeout after 5 minutes!")
            return ""
            
    async def get_user_response_async(self, prompt: str = None) -> str:
        """Get user response - async version."""
        # Use sync version in thread
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.get_user_response, prompt)
        
    # Method Overrides
    
    def _llm_response_with_context(self, agent: ChatAgent, *args, **kwargs):
        """Override for llm_response."""
        logger.info("🔧 _llm_response_with_context called")
        
        # Reset cached message flag at the start of a new response cycle
        self._cached_message_sent = False
        
        # Track if streaming is being used
        self._stream_started = False
        
        response = agent._original_llm_response(*args, **kwargs)
        
        # Don't send anything here - let llm_response_messages handle it
        logger.info("SYNC: llm_response completed, not sending message here")
            
        return response
        
    async def _llm_response_async_with_context(self, agent: ChatAgent, *args, **kwargs):
        """Override for llm_response_async."""
        logger.info("🔧 _llm_response_async_with_context called")
        
        # Track if streaming is being used
        self._stream_started = False
        
        response = await agent._original_llm_response_async(*args, **kwargs)
        
        # Only send complete message if it's cached
        if response and response.content:
            is_cached = hasattr(response, 'metadata') and getattr(response.metadata, 'cached', False)
            if is_cached:
                self._send_assistant_message(response.content)
                logger.info(f"ASYNC: Sent complete message for cached response")
            else:
                logger.info(f"ASYNC: Skipped complete message - will be streamed")
            
        return response
        
    def _user_response_with_context(self, agent: ChatAgent, *args, **kwargs):
        """Override for user_response."""
        logger.info("🔧 _user_response_with_context called")
        # Get user input string
        user_input = self.get_user_response()
        # Return as ChatDocument
        return ChatDocument(
            content=user_input,
            metadata=ChatDocMetaData(sender=Entity.USER)
        )
    
    def _llm_response_messages_with_context(self, agent: ChatAgent, *args, **kwargs):
        """Override for llm_response_messages to add context."""
        logger.info("🔧 _llm_response_messages_with_context called")
        
        # Call original method
        response = agent._original_llm_response_messages(*args, **kwargs)
        
        # This is the primary method for sending messages
        if response and hasattr(response, 'content') and response.content:
            is_cached = hasattr(response, 'metadata') and getattr(response.metadata, 'cached', False)
            if is_cached and not self._cached_message_sent:
                self._send_assistant_message(response.content)
                self._cached_message_sent = True
                logger.debug("PRIMARY: Sent complete message for cached response")
            elif is_cached:
                logger.debug("PRIMARY: Skipped cached message - already sent")
            else:
                logger.debug("PRIMARY: Skipping complete message - will be streamed")
            
        return response
        
    async def _llm_response_messages_async_with_context(self, agent: ChatAgent, *args, **kwargs):
        """Override for llm_response_messages_async."""
        logger.info("🔧 _llm_response_messages_async_with_context called")
        
        # Call original method
        response = await agent._original_llm_response_messages_async(*args, **kwargs)
        
        # Manually trigger callback if Langroid doesn't
        if response and hasattr(response, 'content') and response.content:
            self.show_llm_response(content=response.content, cached=getattr(response.metadata, 'cached', False) if hasattr(response, 'metadata') else False)
            
        return response
        
    def _agent_response_with_context(self, agent: ChatAgent, *args, **kwargs):
        """Override for agent_response to ensure proper interception."""
        response = agent._original_agent_response(*args, **kwargs)
        
        # The show_agent_response callback will be called by Langroid
        # Don't call it here to avoid duplicates
        
        return response
        
    # Utility Methods
    
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
    
    def _queue_message(self, message: dict):
        """Queue a message for WebSocket delivery."""
        def _put_message():
            self.context.message_queue.put_nowait(message)
            
        # Thread-safe queuing
        if self.context.event_loop.is_running():
            self.context.event_loop.call_soon_threadsafe(_put_message)
        else:
            # Fallback for edge cases
            asyncio.run_coroutine_threadsafe(
                self.context.message_queue.put(message),
                self.context.event_loop
            )
            
    def update_task_responders(self, task):
        """
        Update Task's entity responder map after attaching callbacks.
        
        This ensures that any method overrides are used by the Task.
        """
        if hasattr(task, '_entity_responder_map') and hasattr(task.agent, 'entity_responders'):
            fresh_responders = task.agent.entity_responders()
            task._entity_responder_map = dict(fresh_responders)
            logger.info("Updated Task entity responder map")
            
    def detach_from_agent(self, agent: ChatAgent):
        """Detach callbacks and restore original methods."""
        # Restore overridden methods
        if 'llm_response_messages' in self._overridden_methods:
            if hasattr(agent, '_original_llm_response_messages'):
                agent.llm_response_messages = agent._original_llm_response_messages
                
        if 'agent_response' in self._overridden_methods:
            if hasattr(agent, '_original_agent_response'):
                agent.agent_response = agent._original_agent_response
                
        # Clear callbacks
        if hasattr(agent, 'callbacks'):
            agent.callbacks = SimpleNamespace()
            
        logger.info(f"Callbacks detached from agent {agent.config.name}")


def create_websocket_callbacks(
    session_id: str,
    websocket: Any,
    message_queue: asyncio.Queue,
    user_input_queue: queue.Queue
) -> WebSocketCallbacks:
    """
    Factory function to create WebSocket callbacks with proper context.
    
    Args:
        session_id: Unique session identifier
        websocket: WebSocket connection object
        message_queue: Async queue for outgoing messages
        user_input_queue: Sync queue for incoming user input
        
    Returns:
        Configured WebSocketCallbacks instance
    """
    # Get the event loop
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.get_event_loop()
        
    context = CallbackContext(
        session_id=session_id,
        websocket=websocket,
        message_queue=message_queue,
        user_input_queue=user_input_queue,
        event_loop=loop
    )
    
    return WebSocketCallbacks(context)
"""
WebSocket callbacks for Langroid UI integration.

This implementation uses Langroid's native callback system while addressing
the limitations discovered during analysis. It provides a hybrid approach
that maximizes use of callbacks while falling back to method overrides
only where necessary.
"""
import asyncio
import hashlib
import json
import logging
import queue
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Union
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
    current_agent: Optional[Any] = None  # Reference to current agent
    session: Optional[Any] = None  # Reference to the session for pause/resume control
    



class WebSocketCallbacks:
    """
    WebSocket callback implementation that maximizes use of Langroid's native
    callback system while providing robust UI integration.
    
    This class:
    1. Uses native callbacks for all operations where they exist
    2. Provides enhanced context management for callbacks
    3. Only overrides methods where callbacks are insufficient
    4. Handles sync/async bridging for WebSocket communication
    5. Implements coordinated message deduplication to prevent triplication
    
    DEDUPLICATION STRATEGY:
    - PRIMARY SENDER: _llm_response_messages_with_context (sync/async)
      * This is the authoritative source for all LLM response messages
      * Marks messages as sent using content hash tracking
    - SECONDARY SENDERS: show_llm_response and finish_llm_stream callbacks
      * Check if message was already sent by primary before sending
      * Act as fallbacks only if primary didn't handle the message
      * Log when messages are skipped due to deduplication
    This approach reduces message triplication back to single messages.
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
        
        # Message deduplication tracking
        self._sent_message_hashes: Set[str] = set()
        self._current_response_content: Optional[str] = None
        self._message_sent_by_primary = False
        
        logger.info(f"WebSocketCallbacks initialized for session {context.session_id}")
        
    def attach_to_agent(self, agent: ChatAgent):
        """Attach callbacks to a Langroid agent."""
        # Store reference to agent in context
        self.context.current_agent = agent
        
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
        
        # Apply minimal method overrides to ensure callbacks are triggered
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
        
        # Check if this is a StreamingChatAgent and enable token-level streaming
        from .streaming_agent import StreamingChatAgent
        if isinstance(agent, StreamingChatAgent):
            logger.info("🌊 Detected StreamingChatAgent - streaming callbacks will be used!")
        else:
            logger.info("⚠️ Regular ChatAgent - no token-level streaming available")
        
    # Streaming Callbacks
    
    def start_llm_stream(self, **kwargs) -> Callable[[str], None]:
        """Start streaming callback - sync version."""
        logger.info("🌊 start_llm_stream CALLED!")
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
        logger.info(f"🌊 Sent stream_start message with ID: {message_id}")
        
        def stream_token(token: str, event_type=None) -> None:
            """Handle individual stream token."""
            logger.info(f"🌊 Received token: {repr(token[:20])}")
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
        """Finish streaming and send complete message (SECONDARY - checks for duplicates)."""
        stream_trace_id = str(uuid4())[:8]
        logger.info(f"🌊 STREAM[{stream_trace_id}]: finish_llm_stream CALLED! content={content[:50] if content else 'None'}, stream_started={self._stream_started}")
        logger.info(f"🌊 STREAM[{stream_trace_id}]: kwargs: {kwargs}")
        logger.info(f"🌊 STREAM[{stream_trace_id}]: Current stream_id: {self.context.current_stream_id}")
        logger.info(f"🌊 STREAM[{stream_trace_id}]: Current dedup state - sent_hashes: {len(self._sent_message_hashes)}, message_sent_by_primary: {self._message_sent_by_primary}")
        
        if not self._stream_started:
            logger.info(f"⚠️ STREAM[{stream_trace_id}]: Stream not started, returning early")
            return
            
        message_id = self.context.current_stream_id
        logger.info(f"🌊 STREAM[{stream_trace_id}]: Using message_id: {message_id}")
        
        # Send stream end
        logger.info(f"🔚 STREAM[{stream_trace_id}]: Sending stream end message")
        stream_end = StreamEnd(message_id=message_id)
        self._queue_message(stream_end.dict())
        
        # Check if the primary sender has already sent this message
        if content and content.strip():
            content_stripped = content.strip()
            content_hash = self._get_message_hash(content_stripped)
            
            logger.info(f"📝 STREAM[{stream_trace_id}]: Processing content: {content[:100]}...")
            logger.info(f"📝 STREAM[{stream_trace_id}]: Content hash: {content_hash}")
            logger.info(f"📝 STREAM[{stream_trace_id}]: Content length: {len(content_stripped)}")
            
            already_sent = self._is_message_already_sent(content_stripped)
            logger.info(f"🔍 STREAM[{stream_trace_id}]: Already sent check: {already_sent}")
            logger.info(f"🔍 STREAM[{stream_trace_id}]: Current sent hashes: {self._sent_message_hashes}")
            
            if already_sent:
                logger.info(f"🚫 STREAM[{stream_trace_id}]: finish_llm_stream - complete message already sent by primary, skipping: {content[:50]}...")
                self._stream_started = False
                self.context.current_stream_id = None
                logger.info(f"🏁 STREAM[{stream_trace_id}]: finish_llm_stream finished (skipped duplicate)")
                return
            
            # If primary hasn't sent it, send complete message as fallback
            logger.info(f"🚀 STREAM[{stream_trace_id}]: Primary didn't send message, sending complete message as fallback")
            complete_msg = CompleteMessage(
                message=ChatMessage(
                    id=message_id,
                    content=content,
                    sender="assistant"
                )
            )
            logger.info(f"📦 STREAM[{stream_trace_id}]: Created fallback complete message with ID: {message_id}")
            self._queue_message(complete_msg.dict())
            logger.info(f"📌 STREAM[{stream_trace_id}]: Marking message as sent")
            self._mark_message_as_sent(content_stripped)
            logger.info(f"⚠️ STREAM[{stream_trace_id}]: FALLBACK - finish_llm_stream sent complete message (primary didn't handle): {content[:50]}...")
        else:
            logger.info(f"⚠️ STREAM[{stream_trace_id}]: Empty content, skipping complete message")
        
        self._stream_started = False
        self.context.current_stream_id = None
        logger.info(f"🏁 STREAM[{stream_trace_id}]: finish_llm_stream finished")
        
    def cancel_llm_stream(self) -> None:
        """Cancel streaming (e.g., when cached response found)."""
        if self._stream_started:
            # For now, just send stream end
            stream_end = StreamEnd(message_id=self.context.current_stream_id)
            self._queue_message(stream_end.dict())
            self._stream_started = False
            
    # Display Callbacks
    
    def show_llm_response(self, content: str, is_tool: bool = False, cached: bool = False, **kwargs) -> None:
        """Show LLM response - called for non-streaming responses (SECONDARY - checks for duplicates)."""
        secondary_trace_id = str(uuid4())[:8]
        logger.info(f"🎯 SECONDARY[{secondary_trace_id}]: show_llm_response CALLED! content={content[:50] if content else 'None'}, is_tool={is_tool}, cached={cached}")
        logger.info(f"🎯 SECONDARY[{secondary_trace_id}]: kwargs: {kwargs}")
        logger.info(f"🎯 SECONDARY[{secondary_trace_id}]: Current dedup state - sent_hashes: {len(self._sent_message_hashes)}, message_sent_by_primary: {self._message_sent_by_primary}")
        
        # Check if the primary sender has already sent this message
        if content and content.strip():
            content_stripped = content.strip()
            content_hash = self._get_message_hash(content_stripped)
            
            logger.info(f"📝 SECONDARY[{secondary_trace_id}]: Processing content: {content[:100]}...")
            logger.info(f"📝 SECONDARY[{secondary_trace_id}]: Content hash: {content_hash}")
            logger.info(f"📝 SECONDARY[{secondary_trace_id}]: Content length: {len(content_stripped)}")
            
            already_sent = self._is_message_already_sent(content_stripped)
            logger.info(f"🔍 SECONDARY[{secondary_trace_id}]: Already sent check: {already_sent}")
            logger.info(f"🔍 SECONDARY[{secondary_trace_id}]: Current sent hashes: {self._sent_message_hashes}")
            
            if already_sent:
                logger.info(f"🚫 SECONDARY[{secondary_trace_id}]: show_llm_response - message already sent by primary, skipping: {content[:50]}...")
                return
            
            # If primary hasn't sent it yet, send it as fallback
            logger.info(f"🚀 SECONDARY[{secondary_trace_id}]: Primary didn't send message, sending as fallback")
            message_id = str(uuid4())
            message = CompleteMessage(
                message=ChatMessage(
                    id=message_id,
                    content=content,
                    sender="assistant"
                )
            )
            logger.info(f"📦 SECONDARY[{secondary_trace_id}]: Created fallback message with ID: {message_id}")
            self._queue_message(message.dict())
            logger.info(f"📌 SECONDARY[{secondary_trace_id}]: Marking message as sent")
            self._mark_message_as_sent(content_stripped)
            logger.info(f"⚠️ SECONDARY[{secondary_trace_id}]: FALLBACK - show_llm_response sent message (primary didn't handle): {content[:50]}...")
        else:
            logger.info(f"⚠️ SECONDARY[{secondary_trace_id}]: Empty content, skipping")
            
        logger.info(f"🏁 SECONDARY[{secondary_trace_id}]: show_llm_response finished")
        
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
        
        # Check if we need to wait for WebSocket reconnection
        if self.context.session and hasattr(self.context.session, '_pause_event'):
            pause_event = self.context.session._pause_event
            if not pause_event.is_set():
                logger.info("🚫 Task paused, waiting for WebSocket reconnection...")
                pause_event.wait(timeout=300)  # Wait up to 5 minutes for reconnection
                if pause_event.is_set():
                    logger.info("✅ Task resumed after WebSocket reconnection")
                    
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
        
        # Reset deduplication state at the start of a new response cycle
        self._reset_deduplication_state()
        self._cached_message_sent = False
        
        # Track if streaming is being used
        self._stream_started = False
        
        response = agent._original_llm_response(*args, **kwargs)
        
        # Store current response content for deduplication
        if response and hasattr(response, 'content'):
            self._current_response_content = response.content
        
        # Don't send anything here - let llm_response_messages handle it
        logger.info("SYNC: llm_response completed, not sending message here")
            
        return response
        
    async def _llm_response_async_with_context(self, agent: ChatAgent, *args, **kwargs):
        """Override for llm_response_async."""
        logger.info("🔧 _llm_response_async_with_context called")
        
        # Reset deduplication state at the start of a new response cycle
        self._reset_deduplication_state()
        
        # Track if streaming is being used
        self._stream_started = False
        
        response = await agent._original_llm_response_async(*args, **kwargs)
        
        # Store current response content for deduplication
        if response and hasattr(response, 'content'):
            self._current_response_content = response.content
        
        # Don't send messages here - let the primary sender handle it
        logger.info("ASYNC: llm_response_async completed, not sending message here")
            
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
        """Override for llm_response_messages to add context - PRIMARY MESSAGE SENDER."""
        primary_trace_id = str(uuid4())[:8]
        logger.info(f"🔧 PRIMARY[{primary_trace_id}]: _llm_response_messages_with_context called (SYNC)")
        logger.info(f"🔧 PRIMARY[{primary_trace_id}]: Args: {args}, Kwargs: {kwargs}")
        logger.info(f"🔧 PRIMARY[{primary_trace_id}]: Agent: {agent.config.name}")
        logger.info(f"🔧 PRIMARY[{primary_trace_id}]: Current dedup state - sent_hashes: {len(self._sent_message_hashes)}, message_sent_by_primary: {self._message_sent_by_primary}")
        
        # Call original method
        logger.info(f"⚙️ PRIMARY[{primary_trace_id}]: Calling original method...")
        response = agent._original_llm_response_messages(*args, **kwargs)
        logger.info(f"⚙️ PRIMARY[{primary_trace_id}]: Original method returned: {type(response)}, has_content: {hasattr(response, 'content') if response else False}")
        
        # This is the PRIMARY and AUTHORITATIVE method for sending messages
        if response and hasattr(response, 'content') and response.content:
            content = response.content.strip()
            content_hash = self._get_message_hash(content)
            
            logger.info(f"📝 PRIMARY[{primary_trace_id}]: Processing response content: {content[:100]}...")
            logger.info(f"📝 PRIMARY[{primary_trace_id}]: Content hash: {content_hash}")
            logger.info(f"📝 PRIMARY[{primary_trace_id}]: Content length: {len(content)}")
            
            # Check if we've already sent this message
            already_sent = self._is_message_already_sent(content)
            logger.info(f"🔍 PRIMARY[{primary_trace_id}]: Already sent check: {already_sent}")
            logger.info(f"🔍 PRIMARY[{primary_trace_id}]: Current sent hashes: {self._sent_message_hashes}")
            
            if already_sent:
                logger.info(f"🚫 PRIMARY[{primary_trace_id}]: Message already sent, skipping duplicate: {content[:50]}...")
                return response
            
            # Send the message and mark as sent by primary
            logger.info(f"🚀 PRIMARY[{primary_trace_id}]: Sending assistant message via _send_assistant_message")
            self._send_assistant_message(content)
            logger.info(f"📌 PRIMARY[{primary_trace_id}]: Marking message as sent")
            self._mark_message_as_sent(content)
            self._message_sent_by_primary = True
            
            # Update cached message tracking
            is_cached = hasattr(response, 'metadata') and getattr(response.metadata, 'cached', False)
            logger.info(f"📄 PRIMARY[{primary_trace_id}]: Response cached status: {is_cached}")
            if is_cached:
                self._cached_message_sent = True
                logger.info(f"✅ PRIMARY[{primary_trace_id}]: Sent complete message for cached response: {content[:50]}...")
            else:
                logger.info(f"✅ PRIMARY[{primary_trace_id}]: Sent complete message (non-cached response): {content[:50]}...")
        else:
            logger.info(f"⚠️ PRIMARY[{primary_trace_id}]: No content to send - response: {response}, has_content: {hasattr(response, 'content') if response else False}")
            
        logger.info(f"🏁 PRIMARY[{primary_trace_id}]: _llm_response_messages_with_context finished")
        return response
        
    async def _llm_response_messages_async_with_context(self, agent: ChatAgent, *args, **kwargs):
        """Override for llm_response_messages_async - PRIMARY MESSAGE SENDER (async)."""
        primary_async_trace_id = str(uuid4())[:8]
        logger.info(f"🔧 PRIMARY_ASYNC[{primary_async_trace_id}]: _llm_response_messages_async_with_context called (ASYNC)")
        logger.info(f"🔧 PRIMARY_ASYNC[{primary_async_trace_id}]: Args: {args}, Kwargs: {kwargs}")
        logger.info(f"🔧 PRIMARY_ASYNC[{primary_async_trace_id}]: Agent: {agent.config.name}")
        logger.info(f"🔧 PRIMARY_ASYNC[{primary_async_trace_id}]: Current dedup state - sent_hashes: {len(self._sent_message_hashes)}, message_sent_by_primary: {self._message_sent_by_primary}")
        
        # Call original method
        logger.info(f"⚙️ PRIMARY_ASYNC[{primary_async_trace_id}]: Calling original async method...")
        response = await agent._original_llm_response_messages_async(*args, **kwargs)
        logger.info(f"⚙️ PRIMARY_ASYNC[{primary_async_trace_id}]: Original async method returned: {type(response)}, has_content: {hasattr(response, 'content') if response else False}")
        
        # This is the PRIMARY and AUTHORITATIVE method for sending messages (async version)
        if response and hasattr(response, 'content') and response.content:
            content = response.content.strip()
            content_hash = self._get_message_hash(content)
            
            logger.info(f"📝 PRIMARY_ASYNC[{primary_async_trace_id}]: Processing response content: {content[:100]}...")
            logger.info(f"📝 PRIMARY_ASYNC[{primary_async_trace_id}]: Content hash: {content_hash}")
            logger.info(f"📝 PRIMARY_ASYNC[{primary_async_trace_id}]: Content length: {len(content)}")
            
            # Check if we've already sent this message
            already_sent = self._is_message_already_sent(content)
            logger.info(f"🔍 PRIMARY_ASYNC[{primary_async_trace_id}]: Already sent check: {already_sent}")
            logger.info(f"🔍 PRIMARY_ASYNC[{primary_async_trace_id}]: Current sent hashes: {self._sent_message_hashes}")
            
            if already_sent:
                logger.info(f"🚫 PRIMARY_ASYNC[{primary_async_trace_id}]: Message already sent, skipping duplicate: {content[:50]}...")
                return response
            
            # Send the message and mark as sent by primary
            logger.info(f"🚀 PRIMARY_ASYNC[{primary_async_trace_id}]: Sending assistant message via _send_assistant_message")
            self._send_assistant_message(content)
            logger.info(f"📌 PRIMARY_ASYNC[{primary_async_trace_id}]: Marking message as sent")
            self._mark_message_as_sent(content)
            self._message_sent_by_primary = True
            
            # Update cached message tracking
            is_cached = hasattr(response, 'metadata') and getattr(response.metadata, 'cached', False)
            logger.info(f"📄 PRIMARY_ASYNC[{primary_async_trace_id}]: Response cached status: {is_cached}")
            if is_cached:
                self._cached_message_sent = True
                logger.info(f"✅ PRIMARY_ASYNC[{primary_async_trace_id}]: Sent complete message for cached response: {content[:50]}...")
            else:
                logger.info(f"✅ PRIMARY_ASYNC[{primary_async_trace_id}]: Sent complete message (non-cached response): {content[:50]}...")
        else:
            logger.info(f"⚠️ PRIMARY_ASYNC[{primary_async_trace_id}]: No content to send - response: {response}, has_content: {hasattr(response, 'content') if response else False}")
            
        logger.info(f"🏁 PRIMARY_ASYNC[{primary_async_trace_id}]: _llm_response_messages_async_with_context finished")
        return response
        
    def _agent_response_with_context(self, agent: ChatAgent, *args, **kwargs):
        """Override for agent_response to ensure proper interception."""
        response = agent._original_agent_response(*args, **kwargs)
        
        # The show_agent_response callback will be called by Langroid
        # Don't call it here to avoid duplicates
        
        return response
        
    # Utility Methods
    
    def _get_message_hash(self, content: str) -> str:
        """Generate a hash for message content to track duplicates with detailed logging."""
        dedup_trace_id = str(uuid4())[:8]
        logger.info(f"🔑 DEDUP[{dedup_trace_id}]: Generating hash for content: {content[:100]}...")
        logger.info(f"🔑 DEDUP[{dedup_trace_id}]: Content length: {len(content)}")
        
        # Use SHA256 hash of content
        content_bytes = content.encode('utf-8')
        hash_full = hashlib.sha256(content_bytes).hexdigest()
        hash_short = hash_full[:16]
        
        logger.info(f"🔑 DEDUP[{dedup_trace_id}]: Generated hash: {hash_short} (full: {hash_full})")
        return hash_short
    
    def _is_message_already_sent(self, content: str) -> bool:
        """Check if a message with this content has already been sent with detailed logging."""
        dedup_check_trace_id = str(uuid4())[:8]
        logger.info(f"🔍 DEDUP_CHECK[{dedup_check_trace_id}]: Checking if message already sent: {content[:100]}...")
        logger.info(f"🔍 DEDUP_CHECK[{dedup_check_trace_id}]: Content length: {len(content) if content else 0}")
        
        if not content or not content.strip():
            logger.info(f"🔍 DEDUP_CHECK[{dedup_check_trace_id}]: Empty content, returning True (don't send empty messages)")
            return True  # Don't send empty messages
        
        content_stripped = content.strip()
        message_hash = self._get_message_hash(content_stripped)
        
        logger.info(f"🔍 DEDUP_CHECK[{dedup_check_trace_id}]: Message hash: {message_hash}")
        logger.info(f"🔍 DEDUP_CHECK[{dedup_check_trace_id}]: Current sent hashes ({len(self._sent_message_hashes)}): {list(self._sent_message_hashes)}")
        
        already_sent = message_hash in self._sent_message_hashes
        logger.info(f"🔍 DEDUP_CHECK[{dedup_check_trace_id}]: Already sent result: {already_sent}")
        
        return already_sent
    
    def _mark_message_as_sent(self, content: str) -> None:
        """Mark a message as sent to prevent duplicates with detailed logging."""
        dedup_mark_trace_id = str(uuid4())[:8]
        logger.info(f"📌 DEDUP_MARK[{dedup_mark_trace_id}]: Marking message as sent: {content[:100]}...")
        logger.info(f"📌 DEDUP_MARK[{dedup_mark_trace_id}]: Content length: {len(content) if content else 0}")
        
        if content and content.strip():
            content_stripped = content.strip()
            message_hash = self._get_message_hash(content_stripped)
            
            logger.info(f"📌 DEDUP_MARK[{dedup_mark_trace_id}]: Generated hash: {message_hash}")
            logger.info(f"📌 DEDUP_MARK[{dedup_mark_trace_id}]: Before adding - sent hashes ({len(self._sent_message_hashes)}): {list(self._sent_message_hashes)}")
            
            self._sent_message_hashes.add(message_hash)
            
            logger.info(f"📌 DEDUP_MARK[{dedup_mark_trace_id}]: After adding - sent hashes ({len(self._sent_message_hashes)}): {list(self._sent_message_hashes)}")
            logger.info(f"✅ DEDUP_MARK[{dedup_mark_trace_id}]: Successfully marked message as sent: {message_hash}")
        else:
            logger.info(f"⚠️ DEDUP_MARK[{dedup_mark_trace_id}]: Empty content, not marking as sent")
    
    def _reset_deduplication_state(self) -> None:
        """Reset deduplication state for a new response cycle."""
        self._current_response_content = None
        self._message_sent_by_primary = False
        # Clear message hashes to allow legitimate duplicate responses (e.g., MockLM same responses)
        self._sent_message_hashes.clear()
        logger.debug("🔄 Reset deduplication state for new response cycle, cleared message hashes")
    
    def _send_assistant_message(self, content: str):
        """Send an assistant message to the UI with detailed logging."""
        assistant_trace_id = str(uuid4())[:8]
        logger.info(f"🤖 ASSISTANT[{assistant_trace_id}]: _send_assistant_message called")
        logger.info(f"🤖 ASSISTANT[{assistant_trace_id}]: Content: {content[:100] if content else 'None'}...")
        logger.info(f"🤖 ASSISTANT[{assistant_trace_id}]: Content length: {len(content) if content else 0}")
        
        # Don't send empty messages
        if not content or not content.strip():
            logger.warning(f"⚠️ ASSISTANT[{assistant_trace_id}]: Skipping empty assistant message")
            return
            
        msg_id = str(uuid4())
        logger.info(f"🤖 ASSISTANT[{assistant_trace_id}]: Generated message ID: {msg_id}")
        
        message = CompleteMessage(
            message=ChatMessage(
                id=msg_id,
                content=content,
                sender="assistant"
            )
        )
        
        logger.info(f"🤖 ASSISTANT[{assistant_trace_id}]: Created CompleteMessage with ChatMessage")
        logger.info(f"🤖 ASSISTANT[{assistant_trace_id}]: Calling _queue_message...")
        self._queue_message(message.dict())
        logger.info(f"✅ ASSISTANT[{assistant_trace_id}]: Message queued successfully")
    
    def _queue_message(self, message: dict):
        """Queue a message for WebSocket transmission with detailed logging."""
        msg_type = message.get('type', 'unknown')
        msg_id = message.get('id', 'no-id')
        content_preview = str(message.get('content', ''))[:50] + '...' if len(str(message.get('content', ''))) > 50 else str(message.get('content', ''))
        
        logger.debug(f"🔥 WEBSOCKET QUEUE: type={msg_type}, id={msg_id}, content='{content_preview}'")
        logger.debug(f"🔥 FULL MESSAGE: {message}")
        
        # Also log the call stack to see where this is coming from
        import traceback
        stack_trace = ''.join(traceback.format_stack()[-3:-1])  # Last 2 frames before this
        logger.debug(f"🔥 CALL STACK:\n{stack_trace}")
        """Queue a message for WebSocket delivery with ultra-detailed logging."""
        import json
        from datetime import datetime
        
        # Generate unique trace ID for this message
        trace_id = str(uuid4())[:8]
        message['_trace_id'] = trace_id
        
        # Extract key message details for logging
        msg_type = message.get('type', 'unknown')
        msg_id = message.get('message_id') or message.get('message', {}).get('id', 'no-id')
        content_preview = ''
        
        if 'message' in message and 'content' in message['message']:
            content = message['message']['content']
            content_preview = content[:50] if content else 'empty'
        elif 'token' in message:
            content_preview = f"TOKEN: {message['token'][:20]}"
        
        # Calculate queue size before adding
        try:
            queue_size_before = self.context.message_queue.qsize()
        except:
            queue_size_before = 'unknown'
        
        logger.info(f"🚀 QUEUE[{trace_id}]: Queuing message type={msg_type}, msg_id={msg_id}, content={content_preview}, queue_size_before={queue_size_before}")
        logger.info(f"📦 QUEUE[{trace_id}]: Full message: {json.dumps(message, indent=2, default=str)[:500]}...")
        
        # Track the call stack to see who's calling this
        import traceback
        stack = traceback.extract_stack()
        caller_info = []
        for frame in stack[-4:-1]:  # Get last 3 frames before this one
            caller_info.append(f"{frame.filename.split('/')[-1]}:{frame.lineno}:{frame.name}")
        logger.info(f"📍 QUEUE[{trace_id}]: Called from: {' -> '.join(caller_info)}")
        
        def _put_message():
            try:
                self.context.message_queue.put_nowait(message)
                # Calculate queue size after adding
                try:
                    queue_size_after = self.context.message_queue.qsize()
                except:
                    queue_size_after = 'unknown'
                logger.info(f"✅ QUEUE[{trace_id}]: Successfully queued, queue_size_after={queue_size_after}")
            except Exception as e:
                logger.error(f"❌ QUEUE[{trace_id}]: Failed to queue message: {e}")
                raise
            
        # Thread-safe queuing
        if self.context.event_loop.is_running():
            logger.info(f"🔄 QUEUE[{trace_id}]: Using call_soon_threadsafe")
            self.context.event_loop.call_soon_threadsafe(_put_message)
        else:
            # Fallback for edge cases
            logger.info(f"🔄 QUEUE[{trace_id}]: Using run_coroutine_threadsafe (fallback)")
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
        # Log deduplication statistics before detaching
        logger.info(f"📊 Deduplication stats for session {self.context.session_id}: "
                   f"tracked {len(self._sent_message_hashes)} unique messages")
        
        # Restore overridden methods
        if 'llm_response_messages' in self._overridden_methods:
            if hasattr(agent, '_original_llm_response_messages'):
                agent.llm_response_messages = agent._original_llm_response_messages
                
        if 'agent_response' in self._overridden_methods:
            if hasattr(agent, '_original_agent_response'):
                agent.agent_response = agent._original_agent_response
                
        # Clear callbacks by removing our attached callbacks
        if hasattr(agent, 'callbacks'):
            for attr_name in ['start_llm_stream', 'start_llm_stream_async', 'finish_llm_stream', 
                             'cancel_llm_stream', 'show_llm_response', 'show_agent_response', 
                             'show_error_message', 'show_start_response', 'get_user_response', 
                             'get_user_response_async']:
                if hasattr(agent.callbacks, attr_name):
                    delattr(agent.callbacks, attr_name)
            
        logger.info(f"Callbacks detached from agent {agent.config.name}")


def create_websocket_callbacks(
    session_id: str,
    websocket: Any,
    message_queue: asyncio.Queue,
    user_input_queue: queue.Queue,
    session: Any = None
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
        event_loop=loop,
        session=session
    )
    
    return WebSocketCallbacks(context)
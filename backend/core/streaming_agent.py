"""
Proof of concept for streaming callbacks in Langroid.
This module patches Langroid classes to enable streaming through callbacks.
"""
import asyncio
import logging
from typing import List, Optional, Callable, Any, Dict, Union
from uuid import uuid4

import langroid as lr
from langroid.agent.chat_agent import ChatAgent, ChatAgentConfig
from langroid.agent.chat_document import ChatDocument, ChatDocMetaData
from langroid.language_models.openai_gpt import OpenAIGPT, OpenAIGPTConfig
from langroid.mytypes import Entity

logger = logging.getLogger(__name__)


class StreamingChatAgent(ChatAgent):
    """
    Extended ChatAgent that supports streaming callbacks.
    """
    
    def __init__(self, config: ChatAgentConfig):
        super().__init__(config)
        self._stream_callback = None
    
    async def llm_response_messages_async(
        self, 
        messages: List[ChatDocument],
        output_len: Optional[int] = None,
        tool_choice: Optional[str] = None,
        tools: Optional[List[Any]] = None,
        functions: Optional[List[Any]] = None,
        **kwargs
    ) -> Optional[ChatDocument]:
        """Override to add streaming callback support."""
        
        # Check if streaming is enabled AND streaming callbacks exist
        if (self.config.llm.stream and 
            hasattr(self, 'callbacks') and 
            hasattr(self.callbacks, 'start_llm_stream')):
            
            logger.info("🚀 StreamingChatAgent: Using streaming callbacks!")
            
            # Create the streaming callback handler
            self._stream_callback = self.callbacks.start_llm_stream()
            
            # Temporarily patch the LLM's _stream_chat method to intercept tokens
            original_stream_chat = None
            if hasattr(self.llm, '_stream_chat'):
                original_stream_chat = self.llm._stream_chat
                self.llm._stream_chat = self._patched_stream_chat
            
            try:
                # Call the original method which will now use our patched _stream_chat
                response = await super().llm_response_messages_async(messages, **kwargs)
                
                # For streaming responses, finish_llm_stream and show_llm_response
                # will be called by the WebSocket callback system - don't call them here
                # to avoid duplicate messages
                
                return response
            finally:
                # Restore original method
                if original_stream_chat:
                    self.llm._stream_chat = original_stream_chat
                self._stream_callback = None
        else:
            # Use original implementation for non-streaming
            # The WebSocket callback system will handle show_llm_response
            response = await super().llm_response_messages_async(messages, **kwargs)
            return response
    
    def _patched_stream_chat(self, messages, **kwargs):
        """Patched version of _stream_chat that intercepts tokens."""
        # Get the original stream generator
        stream = self.llm.__class__._stream_chat(self.llm, messages, **kwargs)
        
        # Wrap it to intercept tokens
        for chunk in stream:
            # Call our callback if we have one
            if self._stream_callback and hasattr(chunk, 'choices') and chunk.choices:
                delta = chunk.choices[0].delta
                if hasattr(delta, 'content') and delta.content:
                    try:
                        self._stream_callback(delta.content)
                    except Exception as e:
                        logger.warning(f"Error calling stream callback: {e}")
            
            # Yield the chunk unchanged
            yield chunk
    
    def llm_response_messages(
        self, 
        messages: List[Any],  # LLMMessage from base class
        output_len: Optional[int] = None,
        tool_choice: Any = 'auto',
        **kwargs
    ) -> ChatDocument:
        """Sync version - delegate to original method to avoid event loop issues."""
        # For now, just call the parent class method to avoid complex async handling
        return super().llm_response_messages(messages, output_len, tool_choice, **kwargs)




def create_streaming_agent(
    name: str = "StreamingAssistant",
    system_message: Optional[str] = None,
    use_mock: Optional[bool] = None
) -> StreamingChatAgent:
    """
    Create a streaming-enabled agent that works with callbacks.
    
    This is a drop-in replacement for create_agent() that adds
    streaming callback support.
    """
    from .agent_factory import create_agent
    
    # Create a normal agent first to get the config
    base_agent = create_agent(name, system_message, use_mock)
    
    # Create our streaming agent with the same config
    streaming_agent = StreamingChatAgent(base_agent.config)
    
    # Copy over any other attributes if needed
    if hasattr(base_agent, 'callbacks'):
        streaming_agent.callbacks = base_agent.callbacks
    
    logger.info(f"Created streaming agent '{name}' with callback support")
    
    return streaming_agent
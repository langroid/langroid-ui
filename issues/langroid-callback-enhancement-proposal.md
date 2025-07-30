# Langroid Callback Enhancement Proposal

## Overview

This document proposes additional callbacks that should be implemented in Langroid to enable robust WebSocket UI integration without requiring method overrides. This builds upon the earlier streaming-focused proposal in `docs/langroid-callback-enhancements-proposal.md` and expands it to cover the complete set of callbacks needed for production UI integration.

## Current State

Langroid currently provides 12 callbacks, but they have critical limitations:
1. **Streaming callbacks exist but aren't triggered** - `start_llm_stream` and `finish_llm_stream` are defined but not called by Langroid's internals
2. **No callback pass-through to LLM clients** - Streaming happens at the LLM client level without callback hooks
3. **Not all callbacks fire reliably** - Many code paths bypass callbacks entirely
4. **No callbacks for task lifecycle, tool usage, or multi-agent coordination**

## Proposed Enhancements

### 1. Fix Existing Streaming Callbacks (Critical - from earlier proposal)

As detailed in the earlier proposal, the streaming callbacks need to be properly integrated:

#### ChatAgent Modifications
```python
async def llm_response_messages_async(self, messages: List[ChatDocument]) -> ChatDocument:
    # Check if streaming is enabled AND streaming callbacks exist
    if self.config.llm.stream and hasattr(self.callbacks, 'start_llm_stream'):
        # Create the streaming callback handler
        stream_callback = self.callbacks.start_llm_stream(
            message_id=str(uuid4()),
            sender="assistant",
            metadata={"model": self.config.llm.chat_model}
        )
        
        # Pass callback to LLM client
        response = await self.llm_client.chat_completion(
            messages=self._format_messages(messages),
            stream=True,
            stream_callback=stream_callback  # New parameter
        )
        
        # Notify completion
        if hasattr(self.callbacks, 'finish_llm_stream'):
            self.callbacks.finish_llm_stream(
                content=response.content,
                cached=response.cached if hasattr(response, 'cached') else False
            )
        
        return response
```

#### LLM Client Interface Updates
```python
async def chat_completion(
    self, 
    messages: List[Dict], 
    stream: bool = False,
    stream_callback: Optional[Callable[[str], None]] = None,
    **kwargs
) -> ChatDocument:
    if stream and stream_callback:
        # Stream with callback
        full_content = ""
        async for chunk in self._stream_chat_completion(messages, **kwargs):
            if chunk.choices[0].delta.content:
                token = chunk.choices[0].delta.content
                stream_callback(token)  # Call the callback with each token
                full_content += token
        
        return ChatDocument(content=full_content)
```

### 2. Guaranteed Response Callbacks

These should be called in ALL code paths where responses are generated:

```python
def before_llm_call(self, messages: List[LLMMessage], **kwargs) -> None:
    """
    Called immediately before any LLM API call.
    Guaranteed to fire for both streaming and non-streaming.
    
    Args:
        messages: The messages being sent to LLM
        kwargs: Additional arguments passed to LLM
    """
    pass

def after_llm_response(self, response: ChatDocument, was_cached: bool = False) -> None:
    """
    Called immediately after LLM response is received.
    Guaranteed to fire for all response types.
    
    Args:
        response: The complete response
        was_cached: Whether this was from cache
    """
    pass
```

### 3. Task Lifecycle Callbacks

For multi-agent systems and complex workflows:

```python
def task_created(self, task: 'Task', parent_task: Optional['Task'] = None) -> None:
    """
    Called when a new task is created.
    
    Args:
        task: The newly created task
        parent_task: The parent task if this is a sub-task
    """
    pass

def task_started(self, task: 'Task') -> None:
    """
    Called when a task begins execution.
    """
    pass

def task_completed(self, task: 'Task', result: Any) -> None:
    """
    Called when a task completes.
    
    Args:
        task: The completed task
        result: The task result
    """
    pass

def task_failed(self, task: 'Task', error: Exception) -> None:
    """
    Called when a task fails with an error.
    """
    pass
```

### 4. Tool Usage Callbacks

Critical for showing tool usage in UI:

```python
def before_tool_use(self, tool_name: str, tool_args: Dict[str, Any]) -> None:
    """
    Called before a tool is invoked.
    
    Args:
        tool_name: Name of the tool being called
        tool_args: Arguments passed to the tool
    """
    pass

def after_tool_use(self, tool_name: str, tool_result: Any) -> None:
    """
    Called after a tool completes.
    
    Args:
        tool_name: Name of the tool that was called
        tool_result: Result from the tool
    """
    pass

def tool_error(self, tool_name: str, error: Exception) -> None:
    """
    Called when a tool encounters an error.
    """
    pass
```

### 5. Message Flow Callbacks

For complete message tracking:

```python
def message_queued(self, message: Message, source: str) -> None:
    """
    Called when any message is added to the message history.
    
    Args:
        message: The message being queued
        source: Where the message originated ('user', 'llm', 'tool', 'system')
    """
    pass

def message_filtered(self, message: Message, reason: str) -> None:
    """
    Called when a message is filtered out (e.g., empty content).
    
    Args:
        message: The filtered message
        reason: Why it was filtered
    """
    pass
```

### 6. Connection State Callbacks

For robust WebSocket/UI integration:

```python
def connection_state_changed(self, state: str, details: Dict[str, Any]) -> None:
    """
    Called when UI connection state changes.
    
    Args:
        state: 'connected', 'disconnected', 'reconnecting'
        details: Additional connection details
    """
    pass

def should_pause_execution(self) -> bool:
    """
    Called to check if execution should pause (e.g., UI disconnected).
    
    Returns:
        True if execution should pause
    """
    return False
```

## Implementation Requirements

### 1. Guaranteed Execution

All callbacks must be guaranteed to execute when their corresponding events occur. This requires:
- Callbacks integrated into base classes (`ChatAgent`, `Task`)
- All code paths that generate responses must trigger callbacks
- No conditional callback execution based on agent type

### 2. Streaming Integration

Streaming callbacks should be integrated with all LLM providers:
- OpenAI streaming
- Anthropic streaming  
- Local model streaming
- Any future providers

### 3. Backward Compatibility

New callbacks should:
- Have empty default implementations
- Not break existing code
- Be optional to implement

### 4. Thread Safety

Callbacks may be called from different threads:
- Provide thread-safe callback registration
- Document threading model
- Support both sync and async callbacks

## Example Integration

Here's how the enhanced callbacks would work in practice:

```python
class WebSocketCallbacks(CallbackSystem):
    def start_llm_stream(self):
        self.current_stream_id = str(uuid4())
        
        def handle_token(token: str):
            self.websocket.send_json({
                "type": "stream_token",
                "message_id": self.current_stream_id,
                "token": token
            })
        
        return handle_token
    
    def after_llm_response(self, response, was_cached):
        # Guaranteed to be called for every response
        if was_cached:
            self.send_complete_message(response)
    
    def before_tool_use(self, tool_name, tool_args):
        self.websocket.send_json({
            "type": "tool_start",
            "tool": tool_name,
            "args": tool_args
        })
```

## Benefits

With these callbacks, WebSocket UI integration would:
1. **Not require any method overrides**
2. **Work with all agent types automatically**
3. **Support complex multi-agent workflows**
4. **Provide complete visibility into execution**
5. **Enable robust connection management**

## Priority Order

1. **Streaming callbacks** (start_llm_stream, stream_llm_token, finish_llm_stream) - Critical
2. **Guaranteed response callbacks** (before_llm_call, after_llm_response) - Critical
3. **Tool usage callbacks** - High priority
4. **Task lifecycle callbacks** - Medium priority
5. **Message flow callbacks** - Nice to have
6. **Connection state callbacks** - Nice to have

## Relationship to Earlier Proposal

This proposal **extends** the streaming-focused proposal in `docs/langroid-callback-enhancements-proposal.md` by:

1. **Incorporating all streaming fixes** from the earlier proposal
2. **Adding callbacks for non-streaming scenarios** (tool usage, task lifecycle, etc.)
3. **Ensuring guaranteed callback execution** across all code paths
4. **Supporting multi-agent and complex workflows**

The earlier proposal solved the critical streaming issue. This proposal completes the callback system for all UI integration needs.

## Implementation Priority

Based on the implementation experience:

1. **Fix streaming callbacks** (implement the earlier proposal) - Without this, no real-time streaming
2. **Add guaranteed response callbacks** - Ensure callbacks fire for cached/non-streamed responses  
3. **Add tool usage callbacks** - Critical for showing tool interactions in UI
4. **Add task lifecycle callbacks** - Important for multi-agent systems
5. **Add message flow and connection state callbacks** - Nice to have

## Conclusion

These callback additions, combined with the streaming fixes from the earlier proposal, would make Langroid's callback system complete for modern UI integrations. The key is ensuring callbacks are:
- **Guaranteed to execute** in all relevant code paths
- **Comprehensive** enough to cover all UI needs
- **Consistent** across all agent types
- **Thread-safe** for real-time applications

With these enhancements, developers could build sophisticated UIs without needing to understand Langroid's internals or resort to fragile method overrides.
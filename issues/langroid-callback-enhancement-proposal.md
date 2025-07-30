# Langroid Callback Enhancement Proposal

## Overview

This document proposes additional callbacks that should be implemented in Langroid to enable robust WebSocket UI integration without requiring method overrides. This builds upon the earlier streaming-focused proposal in `docs/langroid-callback-enhancements-proposal.md` and expands it to cover the complete set of callbacks needed for production UI integration.

## Motivation: WebSocket UI Integration

Modern web applications expect real-time, streaming interactions with AI agents. Users want to:
- See tokens appear as they're generated (like ChatGPT)
- Understand what tools the agent is using
- Track progress in multi-agent workflows
- Have responsive UIs that handle disconnections gracefully

To enable this, developers need to build WebSocket-based frontends that communicate with Langroid agents. However, without proper callbacks, they must resort to fragile workarounds like method overrides and monkey-patching.

### The WebSocket UI Pattern

```
React Frontend <--WebSocket--> FastAPI Backend <--Callbacks--> Langroid Agent
```

The frontend needs to receive real-time updates about:
1. **Streaming tokens** - Show response as it's generated
2. **Tool usage** - Display "Agent is searching web..." or "Agent is querying database..."
3. **Task progress** - Show which agent is working in multi-agent systems
4. **Cached responses** - Handle instant responses differently than streamed ones

## Current State

Langroid currently provides 12 callbacks, but they have critical limitations:
1. **Streaming callbacks exist but aren't triggered** - `start_llm_stream` and `finish_llm_stream` are defined but not called by Langroid's internals
2. **No callback pass-through to LLM clients** - Streaming happens at the LLM client level without callback hooks
3. **Not all callbacks fire reliably** - Many code paths bypass callbacks entirely
4. **No callbacks for task lifecycle, tool usage, or multi-agent coordination**

## Current Workarounds (What Developers Must Do)

Without proper callbacks, developers building UIs must resort to:

### 1. Method Overriding
```python
# Developers must override core methods to intercept responses
def _override_methods(self):
    self._original_llm_response = self.agent.llm_response
    self.agent.llm_response = self._llm_response_with_websocket
```

### 2. Monkey Patching for Streaming
```python
# Patch the LLM's internal streaming method to intercept tokens
def _patched_stream_chat(self, messages, **kwargs):
    stream = self.llm.__class__._stream_chat(self.llm, messages, **kwargs)
    for chunk in stream:
        # Manually extract and send tokens to WebSocket
        if hasattr(chunk, 'choices'):
            delta = chunk.choices[0].delta
            if hasattr(delta, 'content') and delta.content:
                self.websocket.send(delta.content)
        yield chunk
```

### 3. Task Entity Responder Map Hacking
```python
# Must update Task's internal responder map after overrides
if hasattr(task, '_entity_responder_map'):
    fresh_responders = agent.entity_responders()
    task._entity_responder_map = dict(fresh_responders)
```

### 4. Message Deduplication
```python
# Without guaranteed callback execution, messages get sent multiple times
# Developers must implement complex deduplication logic
sent_messages = set()
def send_if_not_duplicate(content):
    hash_val = hashlib.sha256(content.encode()).hexdigest()
    if hash_val not in sent_messages:
        sent_messages.add(hash_val)
        websocket.send(content)
```

These workarounds are:
- **Fragile** - Break with Langroid updates
- **Complex** - Require deep understanding of Langroid internals
- **Incomplete** - Don't cover all scenarios (tools, multi-agent, etc.)

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

## Real-World Example: WebSocket UI Integration

Here's how developers would use these callbacks to build a ChatGPT-like UI:

```python
class WebSocketCallbacks(CallbackSystem):
    def __init__(self, websocket):
        self.websocket = websocket
        self.current_stream_id = None
    
    # Streaming callbacks for real-time token display
    def start_llm_stream(self, message_id, sender="assistant", metadata=None):
        self.current_stream_id = message_id
        
        # Notify UI that streaming is starting
        self.websocket.send_json({
            "type": "stream_start",
            "message_id": message_id,
            "sender": sender,
            "model": metadata.get("model") if metadata else None
        })
        
        # Return token handler for LLM client to call
        def handle_token(token: str):
            self.websocket.send_json({
                "type": "stream_token",
                "message_id": self.current_stream_id,
                "token": token
            })
        
        return handle_token
    
    def finish_llm_stream(self, content, cached=False, metadata=None):
        # Notify UI that streaming is complete
        self.websocket.send_json({
            "type": "stream_end",
            "message_id": self.current_stream_id,
            "final_content": content,
            "was_cached": cached
        })
    
    # Tool usage callbacks for showing agent actions
    def before_tool_use(self, tool_name, tool_args):
        self.websocket.send_json({
            "type": "tool_start",
            "tool": tool_name,
            "args": tool_args,
            "message": f"Using {tool_name}..."
        })
    
    def after_tool_use(self, tool_name, tool_result):
        self.websocket.send_json({
            "type": "tool_end",
            "tool": tool_name,
            "success": True,
            "preview": str(tool_result)[:100]  # First 100 chars
        })
    
    # Task lifecycle for multi-agent systems
    def task_created(self, task, parent_task=None):
        self.websocket.send_json({
            "type": "task_created",
            "task_name": task.name,
            "agent_name": task.agent.config.name,
            "parent_task": parent_task.name if parent_task else None
        })
    
    # Connection management
    def should_pause_execution(self):
        # Pause if WebSocket disconnected
        return not self.websocket.connected
```

### Frontend Reception (React Example)

```typescript
// Frontend receives these real-time updates
ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    
    switch(data.type) {
        case 'stream_start':
            // Show typing indicator
            addMessage({
                id: data.message_id,
                content: '',
                sender: 'assistant',
                streaming: true
            });
            break;
            
        case 'stream_token':
            // Append token to message
            updateMessage(data.message_id, {
                content: prev => prev + data.token
            });
            break;
            
        case 'tool_start':
            // Show tool usage indicator
            showToolIndicator(data.tool, data.message);
            break;
            
        case 'task_created':
            // Show which agent is working
            showAgentWorking(data.agent_name);
            break;
    }
};
```

## End Result: Simple Developer Experience

Once these callbacks are implemented in Langroid, developers can build UIs with just:

```python
# Simple, clean integration - no hacks needed!
from langroid import ChatAgent, Task
from my_ui import WebSocketCallbacks

# Create agent with any configuration
agent = ChatAgent(config)

# Attach WebSocket callbacks
agent.callbacks = WebSocketCallbacks(websocket)

# Run task - everything automatically flows to UI
task = Task(agent, interactive=True)
result = task.run()
```

This works for:
- ✅ Simple single agents
- ✅ Multi-agent systems with delegation
- ✅ Tool-using agents (web search, SQL, etc.)
- ✅ Agents with cached responses
- ✅ Any future agent types

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

## Proof of Concept

A working proof-of-concept implementation demonstrating these callback needs can be found at:
- Repository: `langroid-chat-ui/examples/ui/`
- Implementation details: `issues/langroid-native-callbacks-implementation.md`

This implementation currently uses method overrides and monkey-patching to achieve what these callbacks would provide natively. The complex workarounds in that implementation demonstrate precisely why these callbacks are needed in Langroid core.

## Testing the Callbacks

When implementing these callbacks, ensure they:
1. **Fire reliably** - Add unit tests that verify callbacks are called in all scenarios
2. **Handle errors gracefully** - Callback errors shouldn't crash the agent
3. **Support async contexts** - Many UI frameworks are async
4. **Are thread-safe** - WebSocket handlers often run in different threads

Example test:
```python
def test_streaming_callbacks_fire():
    callback_tokens = []
    
    class TestCallbacks:
        def start_llm_stream(self, **kwargs):
            return lambda token: callback_tokens.append(token)
    
    agent = ChatAgent(config)
    agent.callbacks = TestCallbacks()
    
    response = agent.llm_response("Hello")
    assert len(callback_tokens) > 0  # Tokens were captured
    assert "".join(callback_tokens) == response  # Full response matches
```

## Conclusion

These callback additions, combined with the streaming fixes from the earlier proposal, would make Langroid's callback system complete for modern UI integrations. The key is ensuring callbacks are:
- **Guaranteed to execute** in all relevant code paths
- **Comprehensive** enough to cover all UI needs
- **Consistent** across all agent types
- **Thread-safe** for real-time applications

With these enhancements, developers could build sophisticated UIs without needing to understand Langroid's internals or resort to fragile method overrides.

The proof-of-concept implementation validates that this approach works and demonstrates the significant simplification these callbacks would provide to developers building modern AI applications.
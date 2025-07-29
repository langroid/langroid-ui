# Langroid Internal Learnings

This document captures important discoveries about Langroid's internal architecture learned while implementing the WebUI system.

## Task Entity Responder Map

### Discovery
When overriding agent methods like `llm_response` and `user_response`, the overrides weren't being called even though they were successfully attached to the agent.

### Root Cause
The `Task` class captures method references during initialization and stores them in `_entity_responder_map`:

```python
# In Task.__init__()
agent_entity_responders = agent.entity_responders()  # Gets method references
self._entity_responder_map = dict(agent_entity_responders)

# Later in Task.response()
response_fn = self._entity_responder_map[cast(Entity, e)]  # Uses stored reference
result = response_fn(self.pending_message)  # Calls original method, not override
```

### The Solution
After creating a Task, update its internal responder map with fresh method references:

```python
task = Task(agent)

# Update the Task's cached method references
if hasattr(task, '_entity_responder_map'):
    from langroid.mytypes import Entity
    fresh_responders = agent.entity_responders()
    task._entity_responder_map = dict(fresh_responders)
```

### Key Learning
Task initialization creates a snapshot of agent methods. Any post-initialization method overrides won't be used unless you manually update the Task's responder map.

## Agent Entity Responders

### What It Is
The `entity_responders()` method returns a list of tuples mapping entities to their handler methods:

```python
def entity_responders(self) -> List[Tuple[Entity, Callable]]:
    return [
        (Entity.AGENT, self.agent_response),
        (Entity.LLM, self.llm_response),
        (Entity.USER, self.user_response),
    ]
```

### How Task Uses It
- Task calls different responder methods based on who is "speaking"
- Entity.USER → calls `user_response()` to get user input
- Entity.LLM → calls `llm_response()` to get LLM response
- Entity.AGENT → calls `agent_response()` for agent-level logic

## Method Call Hierarchy

### LLM Response Flow
Multiple methods are involved in getting an LLM response:

1. `llm_response()` - High-level method, typically called by Task
2. `llm_response_messages()` - Often the actual implementation
3. `llm_response_async()` / `llm_response_messages_async()` - Async variants

### Important Discovery
Some of these methods may be called with different numbers of arguments than expected:
```python
# We got this error:
# TypeError: _llm_response_messages_with_ui() takes from 1 to 2 positional arguments but 4 were given

# Solution: Use *args, **kwargs
def _llm_response_messages_with_ui(self, *args, **kwargs):
    response = self._original_llm_response_messages(*args, **kwargs)
    # ... handle response
```

## Cached Responses

### ChatDocument Metadata
Langroid responses include metadata indicating if they're cached:

```python
# Check if a response is from cache
if hasattr(response, 'metadata') and getattr(response.metadata, 'cached', False):
    # This is a cached response
```

### Streaming vs Cached
- Cached responses don't trigger streaming callbacks
- You need to handle cached responses differently in UI
- Stream callbacks are called only for fresh LLM responses

## Streaming Callbacks

### Callback Injection
Langroid looks for specific callback methods on the agent:

```python
# These callbacks are checked/called during streaming
agent.callbacks.start_llm_stream
agent.callbacks.stream_token  
agent.callbacks.finish_llm_stream
```

### Creating Callbacks Object
If the agent doesn't have a callbacks object, you can create one:

```python
if not hasattr(agent, 'callbacks'):
    from types import SimpleNamespace
    agent.callbacks = SimpleNamespace()

# Then assign your callbacks
agent.callbacks.start_llm_stream = my_start_stream_function
```

## Interactive Task Mode

### How It Works
When `Task(interactive=True)`:
- Task creates a loop: User → Agent → LLM → User → ...
- `user_response()` is called to get user input
- `llm_response()` is called to get agent response
- Loop continues until a done condition is met

### User Input Handling
The default `user_response()` uses `input()` for terminal. For web UI:
- Override `user_response()` to read from a queue/future
- Block until web UI sends user message
- Return as `ChatDocument` with proper metadata

## Thread Safety Considerations

### Sync/Async Bridge
Langroid Task runs in sync context, but WebSocket is async:

```python
# Thread-safe message queuing
def queue_message_threadsafe(message: dict, queue: asyncio.Queue, loop: asyncio.AbstractEventLoop):
    """Queue a message from sync context to async queue."""
    def _queue():
        queue.put_nowait(message)
    
    if loop.is_running():
        loop.call_soon_threadsafe(_queue)
    else:
        asyncio.run_coroutine_threadsafe(queue.put(message), loop)
```

### Event Loop Access
When accessing the event loop from callbacks:
```python
try:
    self._main_loop = asyncio.get_running_loop()
except RuntimeError:
    self._main_loop = None
```

## Message History

### Not Ideal for UI
While `agent.message_history` exists, it's not ideal for web UI because:
- No event/callback when messages are added
- Requires polling to detect changes
- Can miss messages between polls
- Race conditions with multiple readers

### Better Approach
Intercept messages at their source by overriding the responder methods.

## Task Termination

### Done Sequences
Tasks can be configured to terminate on specific sequences:
```python
config = TaskConfig(
    done_sequences=["T,A,L"]  # Tool → Agent → LLM
)
```

### Done If Tool
Tasks can terminate when any tool is generated:
```python
config = TaskConfig(done_if_tool=True)
```

## Method Override Timing

### Critical Timing
1. Create agent
2. Override methods on agent
3. Create Task (captures method references)
4. Update Task's responder map
5. Run Task

Getting this order wrong means overrides won't work.

## Entity Types

### From langroid.mytypes
```python
class Entity(Enum):
    USER = "User"
    LLM = "LLM"  
    AGENT = "Agent"
    SYSTEM = "System"
```

These determine which responder method gets called.

## Key Takeaways

1. **Method references are captured early** - Task initialization snapshots agent methods
2. **Multiple response methods exist** - llm_response, llm_response_messages, etc.
3. **Argument counts vary** - Always use *args, **kwargs for safety
4. **Cached responses are special** - Check metadata.cached
5. **Callbacks need proper setup** - Create callbacks object if missing
6. **Thread safety matters** - Use proper sync/async bridges
7. **Entity types drive execution** - Task routes to methods based on Entity type

These insights are crucial for anyone trying to integrate Langroid with custom UIs or modify its behavior through method overriding.
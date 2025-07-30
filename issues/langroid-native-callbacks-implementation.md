# Langroid Native Callbacks Implementation for WebSocket UI Integration

## Overview

This document describes the implementation of Langroid's native callback system for integrating with a modern WebSocket-based React frontend. The goal was to use Langroid's built-in callbacks instead of method overrides while maintaining streaming support and preventing duplicate messages.

## Background

The original implementation used method overrides to intercept Langroid agent responses and send them to a WebSocket-connected frontend. This approach worked but didn't leverage Langroid's native callback system, which provides 12 different hooks for various stages of agent interaction.

## Implementation Approach

### 1. Hybrid Callback System

We implemented a hybrid approach that combines:
- **Langroid's native callbacks** for handling agent interactions
- **Minimal method overrides** where callbacks alone were insufficient
- **Custom streaming callbacks** patched into Langroid for token-level streaming

### 2. Key Components

#### WebSocketCallbacks (`core/websocket_callbacks.py`)

The main callback implementation that:
- Implements all 12 Langroid callbacks
- Adds custom streaming callbacks (`start_llm_stream`, `stream_llm_token`, `finish_llm_stream`)
- Provides thread-safe message queuing for WebSocket delivery
- Implements SHA256-based message deduplication

Key callbacks implemented:
- `get_user_response()` - Waits for user input from WebSocket
- `show_llm_response()` - Handles non-streaming LLM responses
- `show_agent_response()` - Displays agent responses
- `start_llm_stream()` - Initiates streaming with unique message ID
- `stream_llm_token()` - Sends individual tokens during streaming
- `finish_llm_stream()` - Completes streaming and sends final message

#### StreamingChatAgent (`core/streaming_agent.py`)

A custom agent that extends Langroid's ChatAgent with streaming support:
- Patches the LLM's `_stream_chat` method to intercept tokens
- Provides token-level streaming through callbacks
- Maintains compatibility with Langroid's task system

#### Session Management (`core/session_callbacks.py`)

Manages WebSocket sessions with:
- Browser session ID persistence for reconnections
- WebSocket state tracking (connected/disconnected/reconnecting)
- Task pausing/resuming on WebSocket disconnect/reconnect
- Outgoing message queue clearing on reconnection

### 3. Message Deduplication System

The implementation includes a sophisticated deduplication system to prevent duplicate messages:

#### Backend Deduplication
- **SHA256 hashing** of message content for duplicate detection
- **Primary/Secondary sender pattern**:
  - `_llm_response_messages_with_context` designated as primary sender
  - `show_llm_response` and `finish_llm_stream` as secondary/fallback senders
- **Coordinated deduplication** across all message sending paths

#### Frontend Deduplication
- **Synchronous deduplication** using React `useRef` to prevent race conditions
- **SessionStorage persistence** of message IDs across component remounts
- **WebSocket connection management** to prevent multiple connections

### 4. Critical Fixes

#### React Development Mode Issues
- **Problem**: React StrictMode and development mode caused component remounting
- **Solution**: 
  - Removed StrictMode from `main.tsx`
  - Added synchronous message ID tracking with `useRef`
  - Implemented sessionStorage persistence for message IDs

#### WebSocket Reconnection Race Conditions
- **Problem**: Background tasks continued running during WebSocket disconnections
- **Solution**:
  - Added WebSocket state tracking
  - Implemented task pausing on disconnect
  - Clear stale messages on reconnection

#### Frontend Asynchronous State Updates
- **Problem**: React's async state updates created race conditions in deduplication
- **Solution**:
  - Used `useRef` for synchronous duplicate checking
  - Added connection management to prevent multiple WebSockets

## Technical Implementation Details

### Callback Registration

```python
# Essential method overrides for callback triggering
essential_overrides = {
    'llm_response',
    'llm_response_async', 
    'llm_response_messages',
    'llm_response_messages_async',
    'user_response',
    'agent_response'
}

# Attach callbacks to agent
for method_name in dir(self):
    if not method_name.startswith('_'):
        method = getattr(self, method_name)
        if callable(method) and hasattr(agent, method_name):
            setattr(agent, method_name, method)
```

### Streaming Implementation

```python
def _patched_stream_chat(self, messages, **kwargs):
    """Patched version of _stream_chat that intercepts tokens."""
    stream = self.llm.__class__._stream_chat(self.llm, messages, **kwargs)
    
    for chunk in stream:
        if self._stream_callback and hasattr(chunk, 'choices'):
            delta = chunk.choices[0].delta
            if hasattr(delta, 'content') and delta.content:
                self._stream_callback(delta.content)
        yield chunk
```

### Message Flow

1. **User Input**: WebSocket → `get_user_response()` callback → User input queue
2. **LLM Processing**: 
   - Non-streaming: `show_llm_response()` callback
   - Streaming: `start_llm_stream()` → `stream_llm_token()` → `finish_llm_stream()`
3. **Deduplication**: SHA256 hash checking before WebSocket transmission
4. **Frontend Display**: WebSocket message → React state update → UI render

## Challenges and Solutions

### 1. Callback Limitations
**Challenge**: Langroid's callbacks weren't always triggered in expected code paths.
**Solution**: Implemented minimal method overrides to ensure callbacks are called.

### 2. Streaming Support
**Challenge**: Langroid didn't have native token-level streaming callbacks.
**Solution**: Created StreamingChatAgent with patched `_stream_chat` method.

### 3. Message Duplication
**Challenge**: Multiple code paths sending the same message.
**Solution**: Implemented coordinated deduplication at both backend and frontend.

### 4. React Development Mode
**Challenge**: Component remounting caused state reset and duplicate processing.
**Solution**: Persistent state management and synchronous deduplication.

## Results

The final implementation achieves:
- ✅ Full integration with Langroid's native callback system
- ✅ Token-level streaming support
- ✅ Zero duplicate messages
- ✅ Robust WebSocket connection management
- ✅ Clean separation between Langroid internals and UI layer

## Code Organization

```
backend/
├── core/
│   ├── websocket_callbacks.py    # Main callback implementation
│   ├── streaming_agent.py        # StreamingChatAgent with token interception
│   ├── session_callbacks.py      # WebSocket session management
│   └── agent_factory.py          # Agent creation utilities
├── main_with_callbacks.py        # FastAPI server using callbacks
└── run_with_callbacks.sh         # Launch script

frontend/
└── src/
    └── components/
        └── chat/
            └── ChatContainer.tsx  # React component with deduplication
```

## Lessons Learned

1. **Callbacks need support**: Pure callbacks aren't sufficient; some method overrides are necessary to ensure callbacks are triggered.

2. **Deduplication is critical**: Multiple code paths can send the same message; coordinated deduplication is essential.

3. **Frontend matters**: Backend deduplication alone isn't enough; frontend race conditions must be addressed.

4. **Development vs Production**: React development mode behaviors (StrictMode, HMR) require special handling.

5. **Streaming requires patches**: Token-level streaming needed custom implementation via method patching.

## Future Improvements

1. **Native Langroid streaming callbacks**: Propose adding official streaming callbacks to Langroid.
2. **Callback guarantee**: Ensure all Langroid code paths trigger appropriate callbacks.
3. **WebSocket protocol enhancement**: Add message acknowledgment for guaranteed delivery.
4. **Performance optimization**: Implement message batching for high-frequency token streaming.

## Conclusion

The implementation successfully demonstrates that Langroid's callback system can be used for WebSocket UI integration with proper enhancements. The hybrid approach of callbacks + minimal overrides + custom streaming provides a robust solution that maintains clean separation of concerns while delivering a seamless user experience.
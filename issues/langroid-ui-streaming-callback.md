# Langroid UI Streaming & Callback Implementation

## Overview

This document describes the current implementation of the Langroid Chat UI, which provides a web-based interface for interacting with Langroid agents. The implementation uses WebSockets for real-time bidirectional communication and supports streaming responses.

## Architecture

```
React Frontend (localhost:5173) <--WebSocket--> FastAPI Backend (localhost:8000) <---> Langroid Agent/Task
```

## Key Implementation Details

### Backend Architecture

#### 1. Method Overriding Approach

Instead of using Langroid's callback system (which wasn't firing reliably), we override key agent methods to intercept messages:

```python
# In WebUICallbacks.__init__
def _override_methods(self):
    """Override agent methods to intercept responses."""
    # Store original methods
    self._original_llm_response = self.agent.llm_response
    self._original_user_response = self.agent.user_response
    
    # Override with our WebSocket-aware versions
    self.agent.llm_response = self._llm_response_with_ui
    self.agent.user_response = self._user_response_with_ui
    
    # Also override llm_response_messages if it exists
    if hasattr(self.agent, 'llm_response_messages'):
        self._original_llm_response_messages = self.agent.llm_response_messages
        self.agent.llm_response_messages = self._llm_response_messages_with_ui
```

#### 2. Critical Task Entity Responder Map Fix

Langroid's `Task` class captures method references during initialization. We must update these after our overrides:

```python
# In ChatSession._start_task_loop() after creating Task
if hasattr(self.task, '_entity_responder_map'):
    from langroid.mytypes import Entity
    
    # Get fresh method references from the agent (our overridden methods)
    fresh_responders = self.agent.entity_responders()
    self.task._entity_responder_map = dict(fresh_responders)
```

This ensures the Task uses our overridden methods instead of the original ones.

#### 3. Streaming Implementation

The backend supports real-time token streaming via WebSocket messages:

```python
def start_llm_stream(self):
    """Called when LLM starts streaming."""
    self.current_stream_id = str(uuid4())
    self.stream_started = True
    self.stream_buffer = []
    
    # Track that this message is being streamed
    self.streamed_message_ids.add(self.current_stream_id)
    
    # Send stream start message
    message = StreamStart(
        message_id=self.current_stream_id,
        sender="assistant"
    )
    self._queue_message(message.dict())
    
    # Return token handler
    def stream_token(token: str, event_type=None):
        self.stream_buffer.append(token)
        token_msg = StreamToken(
            message_id=self.current_stream_id,
            token=token
        )
        self._queue_message(token_msg.dict())
    
    return stream_token
```

#### 4. Cached Response Handling

Cached responses don't trigger streaming, so we handle them specially:

```python
def _llm_response_messages_with_ui(self, *args, **kwargs):
    response = self._original_llm_response_messages(*args, **kwargs)
    
    # Only send complete message if it's cached
    if response and hasattr(response, 'content') and response.content:
        is_cached = hasattr(response, 'metadata') and getattr(response.metadata, 'cached', False)
        if is_cached and not self.cached_message_sent:
            self._send_assistant_message(response.content)
            self.cached_message_sent = True
```

#### 5. Empty Stream Detection

When a stream starts but no tokens are sent (cached case), we remove the empty bubble:

```python
def finish_llm_stream(self, content: str = "", is_tool: bool = False):
    if self.current_stream_id:
        # Check if any tokens were actually streamed
        if not self.stream_buffer:
            # No tokens streamed - remove empty bubble
            delete_msg = {
                "type": "delete_message",
                "message_id": self.current_stream_id
            }
            self._queue_message(delete_msg)
```

### Frontend Architecture

#### 1. WebSocket Message Handling

The React frontend handles various message types:

```typescript
// In ChatContainer.tsx
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  
  if (data.type === 'message') {
    // Complete message (cached responses)
    const message: Message = {
      id: data.message.id,
      content: data.message.content,
      sender: data.message.sender,
      timestamp: new Date(data.message.timestamp),
    };
    setMessages(prev => [...prev, message]);
    
  } else if (data.type === 'stream_start') {
    // Start streaming message
    const message: Message = {
      id: data.message_id,
      content: '',
      sender: data.sender || 'assistant',
      timestamp: new Date(),
    };
    setMessages(prev => [...prev, message]);
    setStreamingMessages(prev => new Map(prev).set(data.message_id, ''));
    
  } else if (data.type === 'stream_token') {
    // Accumulate streaming tokens
    setStreamingMessages(prev => {
      const newMap = new Map(prev);
      const currentContent = newMap.get(data.message_id) || '';
      const newContent = currentContent + data.token;
      newMap.set(data.message_id, newContent);
      
      // Update message with accumulated content
      setMessages(messages => messages.map(msg => 
        msg.id === data.message_id 
          ? { ...msg, content: newContent }
          : msg
      ));
      
      return newMap;
    });
    
  } else if (data.type === 'delete_message') {
    // Remove empty streaming bubbles
    setMessages(prev => prev.filter(msg => msg.id !== data.message_id));
  }
};
```

#### 2. Auto-Focus Implementation

After assistant responses, focus returns to the input field:

```typescript
// ChatInput uses forwardRef to expose focus method
export const ChatInput = forwardRef<ChatInputRef, ChatInputProps>(({ onSend, disabled }, ref) => {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  
  useImperativeHandle(ref, () => ({
    focus: () => {
      textareaRef.current?.focus();
    }
  }), []);
  
  // ... rest of component
});

// In ChatContainer, focus after responses
if (data.type === 'message' && message.sender === 'assistant') {
  setTimeout(() => inputRef.current?.focus(), 100);
}
```

### Message Protocol

#### Client → Server
```typescript
interface UserMessage {
  type: "message";
  content: string;
  sessionId?: string;
}
```

#### Server → Client
```typescript
interface StreamStart {
  type: "stream_start";
  message_id: string;
  sender: "assistant";
}

interface StreamToken {
  type: "stream_token";
  message_id: string;
  token: string;
}

interface StreamEnd {
  type: "stream_end";
  message_id: string;
}

interface CompleteMessage {
  type: "message";
  message: {
    id: string;
    content: string;
    sender: "user" | "assistant" | "system";
    timestamp: string;
  };
}

interface DeleteMessage {
  type: "delete_message";
  message_id: string;
}
```

## Key Files

### Backend
- `backend/core/callbacks.py` - WebUICallbacks implementation with method overriding
- `backend/core/session.py` - ChatSession with Task entity responder map fix
- `backend/core/agent_factory.py` - Agent creation with streaming enabled
- `backend/main.py` - FastAPI WebSocket endpoint

### Frontend
- `frontend/src/components/chat/ChatContainer.tsx` - Main chat UI with WebSocket handling
- `frontend/src/components/chat/ChatInput.tsx` - Input field with auto-focus support
- `frontend/src/components/chat/ChatMessage.tsx` - Message display with Markdown support

## Running the Application

```bash
./run.sh
```

The improved `run.sh` script:
- Checks port availability before starting
- Shows which processes are using ports if conflicts exist
- Provides clear instructions for resolving port conflicts
- Verifies backend health before proceeding

## Important Implementation Notes

### 1. Method Override Timing
The WebUICallbacks must override agent methods BEFORE the Task is created, but the Task's entity responder map must be updated AFTER creation.

### 2. Streaming vs Cached Responses
- Streaming responses: Send `stream_start` → `stream_token`(s) → `stream_end`
- Cached responses: Send only `message` (no streaming events)
- Empty streams: Send `delete_message` to remove empty bubble

### 3. Thread Safety
Messages are queued using `queue_message_threadsafe()` to handle the sync→async bridge between Langroid's synchronous methods and the async WebSocket.

### 4. No Input Request Messages
The UI maintains a persistent input field, so we don't send "Enter your message:" prompts that would clutter the conversation.

### 5. Focus Management
The input field automatically receives focus:
- On initial connection
- After each assistant response
- After streaming completes

## Testing

### Working Features
- ✅ WebSocket connection and reconnection
- ✅ User message sending and display
- ✅ Assistant response streaming
- ✅ Cached response handling
- ✅ Markdown rendering
- ✅ Auto-focus on input
- ✅ Proper error handling

### Test with Mock LLM
Set `USE_MOCK_LLM=true` in environment or don't set `OPENAI_API_KEY`.

### Test with Real LLM
Set `OPENAI_API_KEY` and optionally `OPENAI_MODEL` (defaults to gpt-4o-mini).

## Troubleshooting

### Port Conflicts
If you see "Address already in use":
```bash
# Find process on port 8000
lsof -i :8000

# Kill process
kill -9 <PID>

# Or kill all processes on port
lsof -ti :8000 | xargs kill -9
```

### WebSocket Connection Issues
1. Check backend is running: `curl http://localhost:8000/health`
2. Check frontend is running: Open http://localhost:5173
3. Check browser console for errors
4. Check backend logs in terminal

### Messages Not Appearing
1. Verify Task entity responder map is updated (check logs)
2. Ensure WebUICallbacks methods are being called
3. Check for empty content filtering
4. Verify WebSocket messages in browser DevTools

## Future Enhancements

1. **Session Persistence**: Save/restore conversation history
2. **Multi-User Support**: Proper session management
3. **Tool Usage Display**: Show when agents use tools
4. **File Upload**: Support for document chat
5. **Voice Input**: Speech-to-text integration
6. **Export Conversations**: Download chat history
7. **Theme Support**: Dark/light mode toggle
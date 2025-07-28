# Web UI Callbacks Implementation Plan - Fresh Approach

## Executive Summary

After analyzing the existing implementation attempts and the ChainLit pattern, I've identified key issues and propose a fresh approach that properly integrates Langroid's callback system with a web UI. The main challenges are:

1. **Callback Injection Timing**: Callbacks must be injected at the right moment in the agent lifecycle
2. **Async/Sync Bridge**: Proper handling of async WebSocket communication with sync Langroid methods
3. **Streaming Support**: Implementing token-by-token streaming from LLMs to the UI
4. **Session Management**: Clean separation between chat sessions

## Core Architecture

```
Browser <-WebSocket-> FastAPI Server <- Callbacks -> Langroid Agent/Task
                           |
                      Session Manager
                           |
                    WebUICallbacks (injected)
```

## Key Insights from Analysis

### 1. Current Implementation Issues
- Callbacks are being injected but may not be called by the ChatAgent properly
- The `task.run()` method needs specific configuration to use callbacks
- Async/sync bridging is complex and error-prone
- Missing proper callback hooks in the agent's response generation flow

### 2. ChainLit Pattern Success Factors
- Callbacks are injected early in the agent lifecycle
- Uses both sync and async versions of callbacks
- Handles streaming with proper token accumulation
- Clean separation between UI logic and agent logic

## Implementation Strategy

### Phase 1: Core Callback Infrastructure

#### 1.1 Enhanced Callback Injection

```python
class WebUIAgentCallbacks:
    def __init__(self, agent: ChatAgent, websocket: WebSocket, config: WebUICallbackConfig):
        self.agent = agent
        self.websocket = websocket
        self.config = config
        
        # Inject callbacks into the agent's actual response generation flow
        self._override_agent_methods()
        
    def _override_agent_methods(self):
        """Override key agent methods to ensure callbacks are used"""
        # Store original methods
        self._original_llm_response = self.agent.llm_response
        self._original_user_response = self.agent.user_response
        
        # Replace with callback-aware versions
        self.agent.llm_response = self._llm_response_with_callbacks
        self.agent.user_response = self._user_response_with_callbacks
```

#### 1.2 Proper Async/Sync Bridge

```python
def _create_async_bridge(self):
    """Create a proper bridge between sync callbacks and async WebSocket"""
    # Use a thread-safe queue for communication
    self.message_queue = asyncio.Queue()
    
    # Start a background task to process messages
    asyncio.create_task(self._message_processor())
    
async def _message_processor(self):
    """Process messages from the queue and send via WebSocket"""
    while True:
        message = await self.message_queue.get()
        try:
            await self.websocket.send_json(message)
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
```

### Phase 2: Streaming Implementation

#### 2.1 Token Streaming with Proper Accumulation

```python
def start_llm_stream(self) -> Optional[Callable]:
    """Start streaming and return token handler"""
    self.current_message_id = str(uuid4())
    self.token_buffer = []
    
    # Send stream start message
    asyncio.create_task(self._send_stream_start())
    
    def stream_token(token: str) -> None:
        """Handle individual token"""
        self.token_buffer.append(token)
        # Send token to UI
        asyncio.create_task(self._send_token(token))
    
    return stream_token

async def _send_token(self, token: str):
    """Send individual token to UI"""
    message = {
        "type": "stream_token",
        "message_id": self.current_message_id,
        "token": token
    }
    await self.websocket.send_json(message)
```

#### 2.2 Proper LLM Response Handling

```python
def _llm_response_with_callbacks(self, message=None):
    """Wrapped LLM response method that uses callbacks"""
    # Start streaming if enabled
    if self.config.streaming_enabled:
        stream_handler = self.start_llm_stream()
        # Configure LLM to use streaming
        original_stream = self.agent.config.llm.stream
        self.agent.config.llm.stream = True
        self.agent.config.llm.stream_callback = stream_handler
    
    try:
        # Call original method
        response = self._original_llm_response(message)
        
        # Send complete response
        self.show_llm_response(response.content)
        
        return response
    finally:
        # Restore original streaming setting
        if self.config.streaming_enabled:
            self.agent.config.llm.stream = original_stream
```

### Phase 3: User Input Handling

#### 3.1 Async User Input with Proper Waiting

```python
def _user_response_with_callbacks(self, message=None):
    """Wrapped user response that waits for WebSocket input"""
    # Send input request to UI
    prompt = message.content if message else "Enter your message:"
    
    # Create event to wait for response
    response_event = threading.Event()
    response_value = None
    
    def set_response(value):
        nonlocal response_value
        response_value = value
        response_event.set()
    
    # Register callback for this specific input request
    request_id = str(uuid4())
    self.pending_inputs[request_id] = set_response
    
    # Send input request with ID
    asyncio.create_task(self._send_input_request(request_id, prompt))
    
    # Wait for response
    if response_event.wait(timeout=self.config.user_timeout):
        return lr.ChatDocument(content=response_value, metadata=lr.ChatDocMetaData(sender="user"))
    else:
        raise TimeoutError("User input timeout")
```

### Phase 4: Session Management

#### 4.1 Clean Session Architecture

```python
class ChatSession:
    def __init__(self, websocket: WebSocket):
        self.websocket = websocket
        self.agent = self._create_agent()
        self.callbacks = None
        self.task = None
        
    async def start(self):
        """Initialize session with proper callback injection"""
        # Create and inject callbacks
        self.callbacks = WebUIAgentCallbacks(
            self.agent,
            self.websocket,
            WebUICallbackConfig(streaming_enabled=True)
        )
        
        # Create task with interactive mode
        self.task = Task(
            self.agent,
            interactive=True,
            single_round=False  # Allow continuous conversation
        )
        
        # Run task in background
        self.task_future = asyncio.create_task(
            asyncio.to_thread(self.task.run)
        )
```

#### 4.2 Message Routing

```python
async def handle_user_message(self, content: str):
    """Route user message to waiting callback"""
    if self.callbacks:
        # Find any pending input request
        for request_id, callback in self.callbacks.pending_inputs.items():
            callback(content)
            del self.callbacks.pending_inputs[request_id]
            break
```

### Phase 5: Frontend Integration

#### 5.1 WebSocket Message Protocol

```typescript
// Client -> Server
interface UserMessage {
    type: "message";
    content: string;
    request_id?: string;  // For responding to specific input requests
}

// Server -> Client
interface StreamMessage {
    type: "stream_start" | "stream_token" | "stream_end";
    message_id: string;
    token?: string;  // For stream_token
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

interface InputRequest {
    type: "input_request";
    request_id: string;
    prompt: string;
    timeout: number;
}
```

#### 5.2 React Component Updates

```typescript
// Handle streaming in ChatMessage component
const ChatMessage: React.FC<{message: Message}> = ({message}) => {
    const [streamingContent, setStreamingContent] = useState("");
    
    useEffect(() => {
        if (message.isStreaming) {
            // Accumulate tokens as they arrive
            const handler = (token: string) => {
                setStreamingContent(prev => prev + token);
            };
            // Register handler for this message ID
            streamHandlers[message.id] = handler;
            
            return () => {
                delete streamHandlers[message.id];
            };
        }
    }, [message.id, message.isStreaming]);
    
    return (
        <div className="message">
            {message.isStreaming ? streamingContent : message.content}
        </div>
    );
};
```

## Implementation Steps

### Day 1: Foundation
1. Create new backend structure with proper callback classes
2. Implement WebUIAgentCallbacks with method overriding
3. Set up async/sync bridge with message queue
4. Create basic WebSocket endpoint

### Day 2: Core Functionality
1. Implement streaming callbacks with token handling
2. Add user input handling with timeout support
3. Create session management with proper lifecycle
4. Test with MockLM

### Day 3: Integration
1. Update frontend to handle new message types
2. Implement streaming UI with token accumulation
3. Add input request handling in frontend
4. End-to-end testing

### Day 4: Polish
1. Add error handling and recovery
2. Implement session persistence
3. Add tool usage display
4. Performance optimization

## Key Technical Decisions

### 1. Method Overriding vs Callback Injection
Instead of just setting callbacks on the agent, we override key methods to ensure our callbacks are actually used. This guarantees integration with the agent's response flow.

### 2. Message Queue for Async/Sync Bridge
Using an asyncio Queue with a background processor provides clean separation between sync callback methods and async WebSocket communication.

### 3. Request ID for Input Handling
Each input request gets a unique ID, allowing proper routing of user responses to the correct waiting callback.

### 4. Streaming with Token Accumulation
Frontend accumulates tokens for smooth display while maintaining the complete message for history.

## Testing Strategy

### 1. Unit Tests
- Test callback injection and method overriding
- Test async/sync bridge functionality
- Test message serialization

### 2. Integration Tests
- Test full conversation flow with MockLM
- Test streaming with real LLM (if available)
- Test error scenarios

### 3. E2E Tests
- Test multiple concurrent sessions
- Test reconnection handling
- Test long conversations

## Success Metrics

1. **Responsiveness**: < 50ms latency for message delivery
2. **Streaming**: Smooth token-by-token display
3. **Reliability**: No dropped messages or stuck sessions
4. **Scalability**: Support 100+ concurrent sessions

## Risk Mitigation

### 1. Callback Integration Issues
**Risk**: ChatAgent might not call our callbacks
**Mitigation**: Override methods instead of relying on callback hooks

### 2. Memory Leaks
**Risk**: Sessions not properly cleaned up
**Mitigation**: Implement proper cleanup in session manager with weak references

### 3. WebSocket Stability
**Risk**: Connection drops during conversation
**Mitigation**: Implement reconnection with session recovery

## Conclusion

This implementation plan addresses the core issues in the current approach by:
1. Properly integrating with Langroid's agent lifecycle
2. Creating a robust async/sync bridge
3. Implementing true streaming support
4. Maintaining clean separation of concerns

The key insight is that we need to override agent methods rather than just inject callbacks, ensuring our UI integration is actually used during the conversation flow.
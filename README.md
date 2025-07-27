# Langroid Chat UI - Work in Progress

**Status: Experimental/In Development**

This project aims to create a web-based chat interface for Langroid agents. While the UI is functional, there are significant challenges in properly integrating Langroid's interactive chat system with a WebSocket-based frontend.

## Project Goal

Build a real-time chat application that allows users to interact with Langroid agents through a web browser, demonstrating how to bridge Langroid's terminal-based interaction model with modern web technologies.

## Current Status

- ✅ Frontend UI is complete and functional
- ✅ WebSocket connection established between frontend and backend
- ✅ User messages are received by the backend
- ⚠️ Agent responses are generated but not properly displayed in UI
- ❌ Multiple WebSocket connections cause session management issues
- ❌ Message history synchronization between agent and UI is problematic

## Technical Challenges & Learnings

### Understanding Langroid's Architecture

Langroid is designed primarily for terminal-based interactions with several key components:

1. **ChatAgent**: The core component that manages conversations
2. **Task**: Wraps agents and handles the execution flow
3. **Message History**: Maintains conversation state
4. **Interactive Mode**: Expects synchronous terminal input/output

### Key Integration Challenges

#### 1. Input/Output Redirection

**Challenge**: Langroid's `ChatAgent` uses `Prompt.ask()` to read from stdin, which causes EOF errors in a web environment.

**Solution Attempted**: Created a custom `UIChatAgent` class that overrides the `user_response` method:

```python
class UIChatAgent(ChatAgent):
    def __init__(self, config: ChatAgentConfig, input_queue: Queue[str], running_flag):
        super().__init__(config)
        self.input_queue = input_queue
        self.running_flag = running_flag
    
    def user_response(self, msg: Optional[str] = None) -> Optional[lr.ChatDocument]:
        # Read from queue instead of stdin
        while self.running_flag():
            try:
                user_input = self.input_queue.get(timeout=0.5)
                return self.create_user_response(user_input)
            except Empty:
                continue
```

**Result**: Successfully prevents EOF errors, but message flow still problematic.

#### 2. Message History Synchronization

**Challenge**: The agent's `message_history` needs to be monitored and new messages sent to the frontend.

**Attempted Solution**: Created an async monitor that checks for new messages:

```python
async def _monitor_responses(self):
    last_index = 0
    while self.running:
        history = self.agent.message_history
        if len(history) > last_index:
            for i in range(last_index, len(history)):
                msg = history[i]
                if msg.metadata.sender in [lr.Entity.LLM, lr.Entity.ASSISTANT]:
                    await self._send_to_frontend(msg)
            last_index = len(history)
```

**Issues Found**:
- Multiple WebSocket connections create separate ChatSession instances
- Message history lengths alternate (e.g., 3, 5, 3, 5) indicating concurrent sessions
- Messages are generated but not reaching the correct session's monitor

#### 3. Session Management

**Challenge**: Each WebSocket connection creates a new ChatSession, leading to state management issues.

**Current Implementation**:
```python
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    chat_session = ChatSession(websocket)
    await chat_session.start()
```

**Problems**:
- No session persistence across reconnections
- Multiple concurrent sessions interfere with each other
- No proper cleanup of old sessions

#### 4. Asynchronous vs Synchronous Execution

**Challenge**: Langroid's Task system is primarily synchronous, while WebSocket handling requires async operations.

**Conflicts**:
- `task.run()` blocks the event loop
- Mixing threading (for Task) with asyncio (for WebSocket)
- Queue-based communication adds complexity

### What We've Learned

1. **Langroid's Design Philosophy**: 
   - Built for synchronous, terminal-based interactions
   - Expects immediate user responses
   - Message flow is tightly coupled with the execution model

2. **Key Langroid Components for Web Integration**:
   - `ChatAgent.message_history`: Contains all conversation messages
   - `Entity.LLM` and `Entity.ASSISTANT`: Message sender types to filter
   - `ChatDocument`: Message format with content and metadata
   - `DONE` constant: Must be imported from `langroid.utils.constants`

3. **WebSocket Considerations**:
   - Need robust session management
   - Must handle reconnections gracefully
   - Async message monitoring is complex with Langroid's sync model

## Proposed Solutions (Not Yet Implemented)

### 1. Singleton Session Manager
```python
class SessionManager:
    _instance = None
    _sessions = {}
    
    @classmethod
    def get_session(cls, session_id: str) -> ChatSession:
        if session_id not in cls._sessions:
            cls._sessions[session_id] = ChatSession()
        return cls._sessions[session_id]
```

### 2. Message Queue Architecture
Instead of monitoring message_history, use a dedicated message queue:
```python
class ChatAgent(lr.ChatAgent):
    def __init__(self, config, message_queue):
        super().__init__(config)
        self.message_queue = message_queue
    
    def _respond(self, message):
        response = super()._respond(message)
        self.message_queue.put(response)  # Push to queue
        return response
```

### 3. Event-Driven Approach
Use callbacks instead of polling:
```python
class EventDrivenAgent(lr.ChatAgent):
    def __init__(self, config, on_message_callback):
        super().__init__(config)
        self.on_message = on_message_callback
    
    def _add_message(self, msg):
        super()._add_message(msg)
        if msg.metadata.sender == lr.Entity.LLM:
            self.on_message(msg)
```

## Running the Current Implementation

### Prerequisites
- Python 3.8+
- Node.js 16+
- Langroid installed (`pip install langroid`)

### Setup

1. **Backend**:
   ```bash
   cd backend
   pip install -r requirements.txt
   export OPENAI_API_KEY="your-key"  # Optional
   python main.py
   ```

2. **Frontend**:
   ```bash
   cd frontend
   npm install
   npm run dev
   ```

3. **Access**: Open http://localhost:5173

### What Works
- UI loads and connects to WebSocket
- User can type and send messages
- Backend receives messages
- Agent generates responses (visible in backend logs)

### What Doesn't Work
- Agent responses don't appear in UI
- Multiple sessions cause interference
- Reconnection creates new sessions without cleanup

## Future Work

1. **Proper Session Management**: Implement session IDs and cleanup
2. **Message Queue**: Replace polling with event-driven architecture
3. **State Persistence**: Add Redis/database for session state
4. **Error Handling**: Graceful degradation and reconnection
5. **Testing**: Add comprehensive tests for WebSocket flows

## Contributing

This is an experimental project documenting the challenges of web-enabling Langroid. Contributions focusing on solving the core integration issues are welcome. Please document your attempts and findings, even if unsuccessful.

## Resources

- [Langroid Documentation](https://github.com/langroid/langroid)
- [FastAPI WebSocket Guide](https://fastapi.tiangolo.com/advanced/websockets/)
- [React WebSocket Best Practices](https://www.npmjs.com/package/react-use-websocket)

## License

MIT License - See LICENSE file for details.
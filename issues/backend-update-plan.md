# Backend Update Plan: Integrating POC Callback Approach

## Overview
Apply the proven POC callback approach to the main backend implementation to enable proper Langroid-WebUI integration while maintaining the task loop.

## Current State Analysis

### What's Working in POC
1. **Method Overriding**: Successfully intercepts all agent responses
2. **Task Loop Preservation**: Single `task.run()` maintains conversation state
3. **Thread-Safe Async Bridge**: Proper communication between sync callbacks and async WebSocket
4. **Simple Architecture**: Clean separation of concerns

### Issues with Current Main Backend
1. **Complex Callback System**: Uses ChainLit-inspired callbacks that don't integrate properly
2. **Per-Message Task Creation**: Creates new tasks for each message, losing context
3. **No Method Overriding**: Relies on callback hooks that may not be called

## Proposed Architecture

```
backend/
├── main.py                 # FastAPI app with WebSocket endpoint
├── core/
│   ├── __init__.py
│   ├── agent_factory.py    # Agent creation logic
│   ├── callbacks.py        # Simplified callback implementation
│   └── session.py          # Session management
├── models/
│   ├── __init__.py
│   └── messages.py         # Message types (keep existing)
└── utils/
    ├── __init__.py
    └── async_bridge.py     # Thread-safe async utilities
```

## Implementation Strategy

### Phase 1: Backup and Restructure
1. **Rename current backend** → `backend-old-complex`
2. **Create new clean backend** with simplified structure
3. **Copy only essential files** (models, basic structure)

### Phase 2: Core Implementation

#### 2.1 Simplified Callbacks (`core/callbacks.py`)
```python
class WebUICallbacks:
    """Minimal callback manager using method overriding"""
    
    def __init__(self, agent: ChatAgent, websocket: WebSocket):
        # Store references
        self.agent = agent
        self.websocket = websocket
        self._main_loop = asyncio.get_event_loop()
        
        # Message queues
        self.outgoing_queue = asyncio.Queue()  # To WebSocket
        self.user_input_queue = queue.Queue()  # From WebSocket
        
        # Override agent methods
        self._override_methods()
        
    def _override_methods(self):
        """Override key agent methods for UI integration"""
        self._orig_llm_response = agent.llm_response
        self._orig_user_response = agent.user_response
        
        agent.llm_response = self._llm_response_with_ui
        agent.user_response = self._user_response_with_ui
```

#### 2.2 Session Management (`core/session.py`)
```python
class ChatSession:
    """Manages a single chat session with persistent task loop"""
    
    def __init__(self, session_id: str, websocket: WebSocket):
        self.session_id = session_id
        self.websocket = websocket
        self.agent = create_agent()  # From agent_factory
        self.callbacks = WebUICallbacks(self.agent, websocket)
        self.task = None
        self.task_thread = None
        
    def start(self):
        """Start the persistent task loop"""
        self.task = Task(
            self.agent,
            interactive=True,
            config=TaskConfig(
                addressing_prefix="",  # Clean output
                show_subtask_response=True
            )
        )
        
        # Run task in thread to not block async operations
        self.task_thread = threading.Thread(
            target=self._run_task,
            daemon=True
        )
        self.task_thread.start()
```

#### 2.3 Thread-Safe Async Bridge (`utils/async_bridge.py`)
```python
def queue_message_threadsafe(message: dict, queue: asyncio.Queue, loop: asyncio.AbstractEventLoop):
    """Queue a message from any thread to async queue"""
    asyncio.run_coroutine_threadsafe(
        queue.put(message),
        loop
    )
```

### Phase 3: Main Application (`main.py`)

Keep the WebSocket structure but simplify:
```python
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    session = ChatSession(str(uuid4()), websocket)
    
    try:
        # Start the task loop
        session.start()
        
        # Handle incoming messages
        while True:
            data = await websocket.receive_json()
            session.handle_message(data)
            
    except WebSocketDisconnect:
        session.cleanup()
```

### Phase 4: Configuration and Features

#### 4.1 Agent Configuration
- Support both MockLM and real LLMs via environment variables
- Allow custom system messages
- Enable/disable streaming based on LLM capabilities

#### 4.2 Message Protocol (keep existing)
- Use existing message types from `models/messages.py`
- Maintain compatibility with frontend expectations

#### 4.3 Optional Features (add later)
- Tool usage display
- Streaming support (if LLM supports it)
- Multi-agent orchestration

## Migration Steps

### Day 1: Setup New Structure
1. Create `backend-new/` directory
2. Copy essential files (models, messages)
3. Implement core callback system
4. Test with simple WebSocket client

### Day 2: Integration
1. Implement session management
2. Add agent factory with configuration
3. Create main FastAPI application
4. Test with existing frontend

### Day 3: Polish and Replace
1. Add error handling and logging
2. Implement graceful shutdown
3. Update `run.sh` to use new backend
4. Move old backend to `backend-old-complex`
5. Rename `backend-new` to `backend`

## Key Principles

1. **Simplicity First**: Remove unnecessary complexity
2. **Method Overriding**: Ensure callbacks are always used
3. **Single Task Loop**: Maintain conversation context
4. **Thread Safety**: Proper async/sync bridging
5. **Minimal Dependencies**: Only what's needed

## Testing Strategy

1. **Unit Tests**: Test callback methods individually
2. **Integration Tests**: Test full message flow
3. **Frontend Compatibility**: Ensure existing frontend works unchanged
4. **Performance Tests**: Verify no blocking or delays

## Success Criteria

- [ ] WebSocket connections establish properly
- [ ] Messages flow bidirectionally
- [ ] Task loop persists across messages
- [ ] Context maintained in conversations
- [ ] No errors or warnings in logs
- [ ] Frontend works without modifications

## Rollback Plan

If issues arise:
1. Keep `backend-old-complex` as backup
2. Can quickly swap directories
3. No changes needed to frontend or `run.sh`

## Next Steps

1. Review and approve this plan
2. Create new backend structure
3. Implement core functionality
4. Test thoroughly
5. Deploy and monitor
# Langroid Chat UI Backend

A clean WebSocket-based backend for Langroid chat agents using the method-overriding approach.

## Architecture

This backend uses a proven approach where we override the agent's core methods (`llm_response`, `user_response`) to ensure UI integration, rather than relying on optional callbacks.

### Key Components

- **`core/callbacks.py`**: WebUICallbacks that override agent methods
- **`core/session.py`**: Session management with persistent task loops
- **`core/agent_factory.py`**: Agent creation with LLM configuration
- **`utils/async_bridge.py`**: Thread-safe async/sync bridging

### How It Works

1. Each WebSocket connection gets its own `ChatSession`
2. The session creates a Langroid agent and task
3. The task runs in a separate thread with `interactive=True`
4. Agent methods are overridden to route through WebSocket
5. The task loop persists throughout the conversation

## Running the Backend

```bash
# From the examples/ui directory
python backend/main.py
```

## Environment Variables

Create a `.env` file:

```env
# Use mock LLM (no API key needed)
USE_MOCK_LLM=true

# Or use OpenAI
OPENAI_API_KEY=your_key_here
OPENAI_MODEL=gpt-4o-mini

# Server config
HOST=0.0.0.0
PORT=8000
```

## Key Features

- ✅ Persistent task loop per session
- ✅ Method overriding ensures callbacks work
- ✅ Thread-safe async/sync bridge
- ✅ Clean session management
- ✅ Support for both MockLM and real LLMs
- ✅ Compatible with existing frontend

## Testing

Connect via WebSocket to `ws://localhost:8000/ws` and send:

```json
{
  "type": "message",
  "content": "Hello!"
}
```
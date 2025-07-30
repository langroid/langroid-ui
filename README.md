# Langroid Chat UI

A modern web-based chat interface for Langroid agents, featuring real-time streaming responses and WebSocket communication.

## Overview

This project provides a production-ready web UI for interacting with Langroid agents through a browser. It demonstrates how to properly integrate Langroid's callback system with modern web technologies to create a ChatGPT-like experience.

## Features

- ✅ **Real-time streaming**: See tokens appear as they're generated
- ✅ **WebSocket communication**: Bidirectional real-time updates
- ✅ **Native Langroid callbacks**: Clean integration without method overrides
- ✅ **Session management**: Handles reconnections and browser refreshes
- ✅ **Mock mode**: Test without API keys using Langroid's MockLM
- ✅ **Markdown support**: Rich text formatting in responses
- ✅ **Auto-focus**: Input field stays focused for smooth interaction

## Architecture

```
React Frontend (localhost:5173) <--WebSocket--> FastAPI Backend (localhost:8000) <--Callbacks--> Langroid Agent
```

### Key Components

1. **WebSocketCallbacks** (`backend/core/websocket_callbacks.py`): 
   - Implements Langroid's native callback interface
   - Handles streaming, tool usage, and message flow
   - Provides thread-safe WebSocket communication

2. **StreamingChatAgent** (`backend/core/streaming_agent.py`):
   - Extends Langroid's ChatAgent with token-level streaming
   - Patches LLM client for real-time token interception

3. **React Chat UI** (`frontend/src/components/chat/`):
   - Modern, responsive chat interface
   - Handles streaming updates and reconnections
   - Prevents duplicate messages with robust deduplication

## Quick Start

The easiest way to run the application:

```bash
./run.sh
```

This will:
- Start the backend server on port 8000
- Start the frontend dev server on port 5173
- Open your browser to http://localhost:5173

## Installation

### Prerequisites
- Python 3.8+
- Node.js 16+
- UV (recommended) or pip for Python packages

### Backend Setup

```bash
cd backend

# Using UV (recommended)
uv venv
uv pip install -r requirements.txt

# Or using pip
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Frontend Setup

```bash
cd frontend
npm install
```

## Running the Application

### Option 1: Using the Launch Script (Recommended)

```bash
./run.sh
```

### Option 2: Manual Start

In separate terminals:

```bash
# Backend
cd backend
python main_with_callbacks.py

# Frontend
cd frontend
npm run dev
```

Then open http://localhost:5173 in your browser.

## Configuration

### Using Mock Mode (No API Keys Required)

The application automatically uses MockLM when no OpenAI API key is present. You can also force mock mode:

```bash
# Environment variable
USE_MOCK_LLM=true python main_with_callbacks.py

# Or command line flag
python main_with_callbacks.py --mock
```

### Using OpenAI

Set your API key:

```bash
export OPENAI_API_KEY=sk-your-key-here
python main_with_callbacks.py
```

## Implementation Details

### Callback-Based Architecture

The implementation uses Langroid's native callback system enhanced with streaming support:

```python
# Simple integration - no hacks needed!
agent = StreamingChatAgent(config)
callbacks = WebSocketCallbacks(websocket)
agent.callbacks = callbacks

task = Task(agent, interactive=False)
result = task.run()
```

### Key Features

1. **Token Streaming**: Real-time token display as responses are generated
2. **Message Deduplication**: SHA256-based backend + synchronous frontend deduplication
3. **Session Persistence**: Maintains conversation across reconnections
4. **Error Handling**: Graceful degradation and automatic reconnection

### WebSocket Protocol

Messages follow a simple protocol:

```typescript
// User -> Server
{ type: "message", content: "Hello!", sessionId: "..." }

// Server -> User (streaming)
{ type: "stream_start", message_id: "...", sender: "assistant" }
{ type: "stream_token", message_id: "...", token: "Hello" }
{ type: "stream_end", message_id: "..." }

// Server -> User (complete message)
{ type: "message", message: { id: "...", content: "...", sender: "assistant" } }
```

## Development

### Running Tests

```bash
# Backend tests
cd backend
pytest tests/

# Frontend tests
cd frontend
npm test
```

### Common Issues

1. **Port conflicts**: If ports 8000 or 5173 are in use:
   ```bash
   # Kill processes on ports
   lsof -ti :8000 | xargs kill -9
   lsof -ti :5173 | xargs kill -9
   ```

2. **WebSocket disconnections**: Check browser console and backend logs

3. **Duplicate messages**: Ensure React StrictMode is disabled in development

## Documentation

- Implementation details: `issues/langroid-native-callbacks-implementation.md`
- Callback proposal: `issues/langroid-callback-enhancement-proposal.md`
- Architecture overview: `issues/langroid-ui-streaming-callback.md`

## Future Enhancements

Once Langroid implements the proposed callbacks natively:
- Remove StreamingChatAgent patches
- Simplify WebSocketCallbacks implementation
- Support for more complex agent types automatically

## Contributing

Contributions are welcome! Please focus on:
- Improving the callback integration
- Adding support for more agent types
- Enhancing the UI/UX
- Adding comprehensive tests

## License

MIT License - See LICENSE file for details.
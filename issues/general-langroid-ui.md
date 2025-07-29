# General Langroid UI System Specification

## Overview

This document specifies a general-purpose UI system for Langroid applications, packaged as `langroid-ui`. It will enable any Langroid-based agent or task system to have a web-based chat interface with minimal integration effort.

## Goals

1. **Easy Integration**: Developers can add a web UI to any Langroid application with just a few lines of code
2. **Production Ready**: Suitable for deploying customer-facing applications
3. **Flexible**: Supports single agents, multi-agent systems, and hierarchical tasks
4. **Customizable**: Per-agent styling and specialized message rendering
5. **Maintainable**: Clear separation between Langroid logic and UI concerns

## Architecture

### Package Structure

`langroid-ui` will be a separate Python package that Langroid applications can install:

```bash
pip install langroid-ui
```

### Components

1. **Core System** (Python)
   - WebSocket protocol implementation
   - Callback system for intercepting Langroid agent/task events
   - Message routing and session management
   - Production-ready FastAPI backend

2. **React UI** (TypeScript/React)
   - Modern chat interface
   - Real-time message streaming
   - Tool call visualization
   - Agent customization support

## Integration API

### Primary Method: Explicit Callbacks

```python
from langroid_ui import WebUICallbacks
from langroid import ChatAgent, Task

# Create standard Langroid components
agent = ChatAgent(config)
task = Task(agent)

# Attach UI callbacks
ui_callbacks = WebUICallbacks(
    port=8000,
    host="0.0.0.0",
    title="My Langroid App",
    config=UIConfig(
        # Customization options
    )
)
ui_callbacks.attach(task)

# Start the UI server
ui_callbacks.start()

# Run task - UI automatically receives all events
task.run()
```

### Convenience Method

```python
from langroid_ui import serve_with_ui

task = Task(agent)
serve_with_ui(
    task,
    port=8000,
    title="My Langroid App"
)
```

## Multi-Agent Support

### Agent Identification

Each agent in a system can have custom styling:

```python
ui_config = UIConfig(
    agents={
        "Assistant": AgentStyle(
            avatar="🤖",
            color="#1E88E5",
            name="Assistant"
        ),
        "Researcher": AgentStyle(
            avatar="🔍",
            color="#43A047",
            name="Research Agent"
        )
    }
)
```

### Task Hierarchies

When callbacks are attached to a task, they automatically propagate to all sub-tasks:

- Parent task messages appear at the root level
- Sub-task messages appear nested/indented under their parent
- Users interact only with the top-level task
- Agent-to-agent communication through tools is hidden

Example visualization:
```
User: Analyze this document and summarize it
Assistant: I'll analyze this document for you.
  └─ Researcher: Extracting key points from the document...
  └─ Researcher: Found 3 main themes...
Assistant: Here's the summary: [...]
```

## Message Types and Styling

### Standard Message Types

1. **User Messages** - Right-aligned blue bubbles
2. **Assistant Messages** - Left-aligned with agent avatar
3. **System Messages** - Centered, subtle styling
4. **Error Messages** - Red text with error icon
5. **Thinking Messages** - Italic text for agent reasoning

### Tool Call Visualization

Tool calls are shown as collapsible sections:

```
🔧 web_search("Langroid documentation")
└─ [Click to expand results]
```

When expanded:
```
🔧 web_search("Langroid documentation")
└─ Results:
    ```
    Found 5 results:
    1. Langroid Official Docs - https://langroid.github.io
    2. Getting Started Guide - https://langroid.github.io/start
    ...
    ```
```

Features:
- Tool name and parameters always visible
- Results hidden by default (collapsible)
- Results shown in monospace font
- Consistent styling for all tool types

## Configuration

### UIConfig Schema

```python
@dataclass
class UIConfig:
    # Basic settings
    title: str = "Langroid Chat"
    description: str = ""
    
    # Agent styling
    agents: Dict[str, AgentStyle] = field(default_factory=dict)
    
    # Feature flags
    show_timestamps: bool = True
    show_thinking: bool = True
    enable_markdown: bool = True
    
    # Production settings
    max_message_length: int = 10000
    session_timeout: int = 3600  # seconds
    enable_cors: bool = True
    cors_origins: List[str] = field(default_factory=lambda: ["*"])

@dataclass
class AgentStyle:
    name: str
    avatar: str = "🤖"  # Emoji or URL
    color: str = "#1976D2"  # Hex color
    text_color: Optional[str] = None  # Defaults to white/black based on bg
```

### Environment Configuration

Production deployments can use environment variables:

```bash
LANGROID_UI_PORT=8000
LANGROID_UI_HOST=0.0.0.0
LANGROID_UI_ENV=production
LANGROID_UI_LOG_LEVEL=info
LANGROID_UI_CORS_ORIGINS=https://myapp.com,https://app.myapp.com
```

## WebSocket Protocol

### Client → Server

```typescript
interface UserMessage {
  type: "message";
  content: string;
}

interface Command {
  type: "command";
  command: "stop" | "reset" | "export";
}
```

### Server → Client

```typescript
interface AgentMessage {
  type: "message";
  message: {
    id: string;
    content: string;
    sender: string;  // Agent name
    agent_style?: AgentStyle;
    timestamp: string;
    message_type: "user" | "assistant" | "system" | "error" | "thinking";
    parent_id?: string;  // For nested messages
  };
}

interface ToolCall {
  type: "tool_call";
  tool_call: {
    id: string;
    tool_name: string;
    parameters: Record<string, any>;
    timestamp: string;
    agent: string;
  };
}

interface ToolResult {
  type: "tool_result";
  tool_result: {
    call_id: string;
    result: string;
    error?: string;
    timestamp: string;
  };
}

interface StreamStart {
  type: "stream_start";
  message_id: string;
  sender: string;
  agent_style?: AgentStyle;
  parent_id?: string;
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
```

## Production Features

### Security
- HTTPS/WSS support with SSL certificate configuration
- CORS configuration for cross-origin deployments
- Input validation and sanitization
- Rate limiting hooks (implement your own)

### Reliability
- Automatic reconnection on connection loss
- Session persistence across page reloads
- Graceful error handling
- Health check endpoints

### Performance
- Message streaming for real-time responses
- Efficient WebSocket message batching
- Configurable message history limits
- Optional Redis support for multi-instance deployments

### Monitoring
- Structured logging with configurable levels
- Prometheus metrics endpoints (optional)
- Session analytics hooks

## Deployment Support

### Included
- Production-ready FastAPI application
- Optimized React production build
- Environment-based configuration
- Health and readiness endpoints
- Basic Dockerfile and docker-compose.yml examples

### Not Included
- User authentication (bring your own)
- Database persistence (bring your own)
- Cloud-specific configurations
- Load balancing setup
- CDN configuration

## Example Applications

### Simple Chatbot
```python
from langroid_ui import serve_with_ui
from langroid import ChatAgent, Task

agent = ChatAgent(config)
task = Task(agent)
serve_with_ui(task, port=8000, title="Customer Support Bot")
```

### Multi-Agent System
```python
from langroid_ui import WebUICallbacks, UIConfig, AgentStyle

# Create agents
assistant = ChatAgent(name="Assistant", config=assistant_config)
researcher = ChatAgent(name="Researcher", config=researcher_config)

# Create task hierarchy
main_task = Task(assistant)
research_task = Task(researcher)
main_task.add_subtask(research_task)

# Configure UI
ui_config = UIConfig(
    title="Research Assistant",
    agents={
        "Assistant": AgentStyle(avatar="🤖", color="#1E88E5"),
        "Researcher": AgentStyle(avatar="🔍", color="#43A047")
    }
)

# Attach UI
ui = WebUICallbacks(config=ui_config)
ui.attach(main_task)
ui.start()

# Run
main_task.run()
```

### Customer-Facing Application
```python
from langroid_ui import WebUICallbacks, UIConfig

# Configure for production
ui_config = UIConfig(
    title="AI Legal Assistant",
    description="Get help with legal documents",
    show_thinking=False,  # Hide internal reasoning
    session_timeout=1800,  # 30 minutes
    cors_origins=["https://legalassistant.com"]
)

# Create specialized agent
agent = LegalAssistantAgent(config)
task = Task(agent)

# Deploy with production settings
ui = WebUICallbacks(
    port=8000,
    host="0.0.0.0",
    config=ui_config,
    ssl_certfile="/path/to/cert.pem",
    ssl_keyfile="/path/to/key.pem"
)
ui.attach(task)
ui.start()
```

## Development Workflow

1. **Install Package**
   ```bash
   pip install langroid-ui
   ```

2. **Develop Locally**
   ```python
   serve_with_ui(task, port=8000, dev_mode=True)
   ```

3. **Test Production Build**
   ```bash
   langroid-ui build
   langroid-ui serve --env production
   ```

4. **Deploy**
   - Use provided Dockerfile
   - Or deploy Python backend and React frontend separately
   - Configure environment variables
   - Set up reverse proxy (nginx, etc.)

## Future Enhancements

### Phase 1 (Core Features)
- ✅ Basic chat interface
- ✅ Multi-agent support
- ✅ Tool visualization
- ✅ Production configuration

### Phase 2 (Planned)
- User authentication system
- Conversation persistence
- Export chat history
- Mobile-responsive design
- Accessibility improvements

### Phase 3 (Future)
- Plugin system for custom visualizations
- Voice input/output
- File upload support
- Real-time collaboration
- Analytics dashboard

## Summary

`langroid-ui` will provide a production-ready web interface for any Langroid application with minimal integration effort. It focuses on developer experience while providing the features needed for customer-facing deployments. The explicit callback system ensures flexibility while the convenience methods enable rapid prototyping.
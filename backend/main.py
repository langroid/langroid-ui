import os
import sys
from pathlib import Path
import asyncio
from typing import Dict, Optional
from datetime import datetime
import json

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

# Add the repo root to the path so we can import local packages
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import langroid as lr
from langroid.language_models import MockLMConfig
from langroid.agent.chat_agent import ChatAgent, ChatAgentConfig
from langroid.agent.task import Task
from langroid.language_models.openai_gpt import OpenAIGPTConfig





class Message(BaseModel):
    id: str
    content: str
    sender: str
    timestamp: datetime


class WebCallbacks:
    """Callbacks to bridge Langroid Agent with the WebSocket frontend."""

    def __init__(self, session: "ChatSession") -> None:
        self.session = session
        agent = session.agent
        agent.callbacks.show_agent_response = self.show_message
        agent.callbacks.show_llm_response = self.show_message
        agent.callbacks.get_user_response_async = self.get_user_response_async

    async def get_user_response_async(self, prompt: str) -> str:
        if prompt:
            await self.session._send_bot_message(prompt)
        return await self.session.user_queue.get()

    def show_message(self, content: str, language: str = "text", is_tool: bool = False) -> None:  # noqa: D401
        asyncio.create_task(self.session._send_bot_message(content))


class ChatSession:
    """Manage a chat session using a Langroid agent"""

    def __init__(self, session_id: str, websocket: WebSocket):
        self.session_id = session_id
        self.websocket = websocket
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.user_queue: asyncio.Queue[str] = asyncio.Queue()

        # Create the agent
        self.agent = self._create_agent()
        self.task = Task(self.agent, interactive=True)
        self.callbacks = WebCallbacks(self)
        
    def _create_agent(self) -> ChatAgent:
        """Create agent with appropriate LLM config"""
        # Check if we should force mock mode
        use_mock = os.getenv("USE_MOCK_LLM", "").lower() in ["true", "1", "yes"]
        openai_key = os.getenv("OPENAI_API_KEY")
        
        # Use mock if explicitly requested OR if no API key is present
        if use_mock or not openai_key:
            print("🤖 Using MockLM - no API keys required!")
            config = ChatAgentConfig(
                llm=MockLMConfig(
                    response_dict={
                        "hello": "Hello! I'm a mock Langroid agent running locally without any API keys. How can I help you test the chat interface?",
                        "hi": "Hi there! I'm the mock assistant. Try asking me to calculate something, or ask about the weather!",
                        "help": "I can help you test the chat UI! Try these:\n- Basic math (e.g., 'What is 5 + 7?')\n- Weather queries\n- General conversation\n- Or just chat about anything!",
                        "weather": "I'm a mock model, so I can't check real weather, but let's pretend it's sunny with a chance of debugging! ☀️",
                        "coding": "I love talking about code! This UI is built with React and FastAPI. What would you like to know?",
                        "math|calculate|what is": "Let me pretend to calculate that for you... The answer is 42! (I'm a mock, so I always give the same answer 😄)",
                        "5 + 7|5+7": "5 + 7 equals 12! (Even a mock can do simple math sometimes)",
                        "bye|goodbye": "Goodbye! Thanks for testing the Langroid Chat UI!",
                        "langroid": "Langroid is an amazing framework for building LLM-powered applications! This chat UI demonstrates how to integrate it with web technologies.",
                        "test": "Testing, testing, 1-2-3! The WebSocket connection seems to be working well!",
                        "default": "That's interesting! As a mock agent, I have limited responses, but I'm here to help test the chat interface. What else would you like to try?",
                    },
                    default_response="I'm a mock Langroid agent with limited responses. Try asking about math, weather, or just say hello!"
                ),
                system_message="You are a mock assistant for testing the Langroid Chat UI without API keys."
            )
        else:
            print(f"🔑 Using OpenAI GPT (API key: {openai_key[:8]}...)")
            config = ChatAgentConfig(
                llm=OpenAIGPTConfig(
                    chat_model="gpt-4o-mini",
                    chat_context_length=16000,
                ),
                system_message="""You are a helpful AI assistant in a chat interface. 
                Be concise and friendly in your responses. Remember our conversation history."""
            )
        
        # Return the standard chat agent
        return ChatAgent(config)
    
    
    async def start(self, loop: asyncio.AbstractEventLoop):
        """Start the task loop in the given event loop."""
        self.loop = loop
        asyncio.create_task(self.task.run_async())
        await self._send_bot_message("👋 Connected to Langroid chat!")

    async def send_user_message(self, content: str):
        """Send user input to the running task."""
        await self.user_queue.put(content)

    async def _send_to_frontend(self, data: dict):
        """Send data to frontend via WebSocket"""
        if self.loop and self.websocket:
            try:
                await self.websocket.send_json(data)
            except Exception as e:
                print(f"Error sending to frontend: {e}")

    async def _send_bot_message(self, content: str):
        data = {
            "type": "message",
            "message": {
                "id": f"{datetime.now().timestamp()}",
                "content": content,
                "sender": "assistant",
                "timestamp": datetime.now().isoformat(),
            },
        }
        await self._send_to_frontend(data)
    
    def stop(self):
        """Stop the chat session"""
        self.task.close_loggers()


class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.sessions: Dict[str, ChatSession] = {}

    async def connect(self, websocket: WebSocket, session_id: str):
        await websocket.accept()
        self.active_connections[session_id] = websocket
        
        # Create new chat session
        session = ChatSession(session_id, websocket)
        self.sessions[session_id] = session
        
        # Start the session
        await session.start(asyncio.get_event_loop())

    def disconnect(self, session_id: str):
        if session_id in self.active_connections:
            del self.active_connections[session_id]
            
        if session_id in self.sessions:
            self.sessions[session_id].stop()
            del self.sessions[session_id]


app = FastAPI()

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

manager = ConnectionManager()


@app.get("/")
async def root():
    return {"message": "Langroid Chat API", "status": "running"}


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    session_id = f"session_{id(websocket)}"
    
    await manager.connect(websocket, session_id)
    
    try:
        while True:
            # Receive message from client
            data = await websocket.receive_json()
            
            if data.get("type") == "message":
                user_content = data.get("content", "")
                
                # Get session
                session = manager.sessions.get(session_id)
                if session:
                    # Send user message to agent
                    await session.send_user_message(user_content)
                    
    except WebSocketDisconnect:
        manager.disconnect(session_id)


if __name__ == "__main__":
    import argparse
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Langroid Chat UI Backend")
    parser.add_argument("--mock", action="store_true", help="Force use of MockLM even if API keys are present")
    parser.add_argument("--port", type=int, default=8000, help="Port to run the server on (default: 8000)")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind the server to (default: 0.0.0.0)")
    args = parser.parse_args()
    
    # Load environment variables
    from dotenv import load_dotenv
    load_dotenv()
    
    # Override USE_MOCK_LLM if --mock flag is used
    if args.mock:
        os.environ["USE_MOCK_LLM"] = "true"
        print("🎭 Mock mode enabled via CLI flag")
    
    # Run the server
    uvicorn.run(
        "main:app",
        host=args.host,
        port=args.port,
        reload=True,
        ws_ping_interval=30,
        ws_ping_timeout=30,
    )
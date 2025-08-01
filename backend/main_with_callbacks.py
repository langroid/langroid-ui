#!/usr/bin/env python3
"""
Langroid Chat UI Backend - Using the new callback system.
This version integrates the WebSocketCallbacks implementation.
"""
import os
import sys
import asyncio
import logging
from pathlib import Path
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from dotenv import load_dotenv
import uvicorn

# Add paths
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

# Load environment variables
load_dotenv()

# Import our callback-based session manager
from core.session_callbacks import CallbackSessionManager, WebSocketState
from core.agent_factory import create_agent
from core.streaming_agent import create_streaming_agent
from models.messages import ConnectionStatus

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Set specific logger levels for session debugging
logging.getLogger("core.session_callbacks").setLevel(logging.DEBUG)
logging.getLogger("core.websocket_callbacks").setLevel(logging.DEBUG)
logger = logging.getLogger(__name__)

# Create session manager
session_manager = CallbackSessionManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle application lifecycle."""
    logger.info("Starting Langroid Chat UI Backend with Callbacks")
    yield
    logger.info("Shutting down...")
    await session_manager.cleanup_all()


# Create FastAPI app
app = FastAPI(
    title="Langroid Chat UI Backend (Callbacks)",
    description="WebSocket-based chat interface using native callbacks",
    version="3.0.0",
    lifespan=lifespan
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "http://localhost:8080"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "Langroid Chat UI Backend with Callbacks",
        "version": "3.0.0",
        "endpoints": {
            "websocket": "/ws",
            "health": "/health",
            "test": "/test.html"
        }
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "backend": "langroid-callbacks",
        "active_sessions": len(session_manager.sessions)
    }


@app.get("/test.html")
async def test_page():
    """Serve the test HTML page."""
    return FileResponse("test_streaming.html")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for chat sessions."""
    await websocket.accept()
    
    # Get browser session ID from query params
    browser_session_id = websocket.query_params.get("browser_session_id")
    logger.info(f"WebSocket connection accepted - Browser session: {browser_session_id}")
    
    session = None
    try:
        # Create or get existing session for browser
        session, is_new = await session_manager.create_or_get_session(websocket, browser_session_id)
        
        if is_new:
            # Only create agent and initialize for new sessions
            # Create streaming agent - using mock LLM if no API key
            agent = create_streaming_agent(
                name="Assistant",
                system_message="You are a helpful AI assistant powered by Langroid. Be concise and friendly."
            )
            logger.info(f"Created agent with LLM type: {type(agent.llm)}, streaming: {agent.config.llm.stream}")
            
            # Initialize session with agent
            await session.initialize(agent)
        
        # Start the session (send_greeting only for new sessions)
        await session.start(send_greeting=is_new)
        
        # Handle incoming messages
        while True:
            try:
                # Receive message from WebSocket
                data = await websocket.receive_json()
                await session.handle_message(data)
            except asyncio.CancelledError:
                logger.info(f"WebSocket cancelled for session {session.session_id if session else 'unknown'}")
                break
            except Exception as e:
                if not isinstance(e, WebSocketDisconnect):
                    logger.error(f"Error in WebSocket loop: {e}")
                break
            
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for session {session.session_id if session else 'unknown'}")
        if session:
            # Mark session as disconnected to pause task processing
            session.set_websocket_state(WebSocketState.DISCONNECTED)
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
        if session:
            session.set_websocket_state(WebSocketState.DISCONNECTED)
        try:
            await websocket.send_json({
                "type": "error",
                "data": {"message": str(e)}
            })
        except:
            pass
    finally:
        # Don't immediately clean up session - let it persist for potential React StrictMode reconnection
        # Session cleanup will happen via timeout or explicit cleanup
        if session:
            logger.info(f"WebSocket closed for session {session.session_id}, keeping session alive for potential reconnection")


if __name__ == "__main__":
    # Get port from environment or use default
    port = int(os.getenv("PORT", 8000))
    
    # Run the server
    logger.info(f"Starting server on port {port}")
    logger.info("Using WebSocket callbacks implementation")
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info"
    )
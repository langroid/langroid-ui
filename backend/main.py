#!/usr/bin/env python3
"""
Langroid Chat UI Backend - Clean implementation using method overriding.

This backend maintains a persistent task loop per session, with callbacks
that override agent methods to ensure UI integration.
"""
import os
import sys
import asyncio
import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import uvicorn

# Add the parent directory to the path to import langroid
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

# Also add the backend directory to path for local imports
sys.path.insert(0, str(Path(__file__).parent))

# Load environment variables
load_dotenv()

# Import our components
from core import ChatSession
from core.session import SessionManager
from models.messages import ConnectionStatus

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="Langroid Chat UI Backend",
    description="WebSocket-based chat interface for Langroid agents",
    version="2.0.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create session manager
session_manager = SessionManager()


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "Langroid Chat API",
        "status": "running",
        "version": "2.0.0",
        "approach": "method-overriding",
        "features": ["websocket", "persistent-task-loop", "session-management"]
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "backend": "langroid",
        "active_sessions": session_manager.get_active_sessions()
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    Main WebSocket endpoint for chat communication.
    
    Each connection gets its own session with a persistent task loop.
    """
    await websocket.accept()
    
    session_id = None
    
    try:
        # Create a new session
        session_id = await session_manager.create_session(websocket)
        logger.info(f"WebSocket connection established: {session_id}")
        
        # Handle incoming messages
        while True:
            try:
                # Receive message from WebSocket
                data = await websocket.receive_json()
                logger.debug(f"Session {session_id} received: {data}")
                
                # Route message to session
                await session_manager.handle_message(session_id, data)
                
            except asyncio.CancelledError:
                logger.info(f"WebSocket cancelled: {session_id}")
                break
            except Exception as e:
                if not isinstance(e, WebSocketDisconnect):
                    logger.error(f"Error in WebSocket loop for {session_id}: {e}")
                break
                
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {session_id}")
    except Exception as e:
        logger.error(f"WebSocket error for {session_id}: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Clean up session
        if session_id:
            await session_manager.close_session(session_id)
        try:
            await websocket.close()
        except:
            pass
        logger.info(f"WebSocket cleanup completed: {session_id}")


def main():
    """Run the backend server."""
    # Get configuration from environment
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    
    # Check if we should use MockLM
    use_mock = os.getenv("USE_MOCK_LLM", "").lower() in ["true", "1", "yes"]
    openai_key = os.getenv("OPENAI_API_KEY")
    
    if use_mock or not openai_key:
        logger.info("🤖 Using MockLM - no API keys required!")
        logger.info("💡 To use real LLMs, set OPENAI_API_KEY in .env file")
    else:
        logger.info(f"🔑 Using OpenAI API (key: {openai_key[:8]}...)")
        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        logger.info(f"🧠 Model: {model}")
    
    logger.info(f"🚀 Starting Langroid Chat Backend on {host}:{port}")
    logger.info("📝 Using method-overriding approach for callbacks")
    
    # Run the server
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=True,
        ws_ping_interval=30,
        ws_ping_timeout=30,
        log_level="info",
    )


if __name__ == "__main__":
    main()
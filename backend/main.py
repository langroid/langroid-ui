import os
import sys
from pathlib import Path
from typing import Optional
import asyncio
import logging

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import uvicorn

# Add the parent directory to the path to import langroid
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

# Load environment variables
load_dotenv()

# Import our session manager
from sessions.manager import SessionManager
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
    """Root endpoint"""
    return {
        "message": "Langroid Chat API",
        "status": "running",
        "version": "2.0.0",
        "features": ["websocket", "streaming", "callbacks"]
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "backend": "langroid",
        "streaming": True
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Main WebSocket endpoint for chat communication"""
    await websocket.accept()
    
    session_id = None
    
    try:
        # Create a new session
        session_id = await session_manager.create_session(websocket)
        
        # Send connection status
        try:
            connection_msg = ConnectionStatus(
                status="connected",
                session_id=session_id,
                message=f"Connected to Langroid Chat Backend v2.0 (Sessions: {session_manager.get_active_sessions()})"
            )
            await websocket.send_json(connection_msg.dict())
        except RuntimeError as e:
            logger.warning(f"Could not send connection status: {e}")
            return
        
        # Handle incoming messages
        while True:
            data = await websocket.receive_json()
            logger.info(f"Session {session_id} received: {data}")
            
            # Route message to session
            await session_manager.handle_message(session_id, data)
                
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


if __name__ == "__main__":
    # Get configuration from environment
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    
    # Check if we should use MockLM
    use_mock = os.getenv("USE_MOCK_LLM", "").lower() in ["true", "1", "yes"]
    openai_key = os.getenv("OPENAI_API_KEY")
    
    if use_mock or not openai_key:
        logger.info("🤖 Using MockLM - no API keys required!")
    else:
        logger.info(f"🔑 Using OpenAI API (key: {openai_key[:8]}...)")
    
    # Run the server
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=True,
        ws_ping_interval=30,
        ws_ping_timeout=30,
    )
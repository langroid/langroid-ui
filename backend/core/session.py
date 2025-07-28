"""
Session management for WebSocket connections.
Each session maintains its own agent and persistent task loop.
"""
import asyncio
import logging
import threading
from typing import Optional, Dict, Any
from uuid import uuid4

from fastapi import WebSocket

import langroid as lr
from langroid.agent.task import Task, TaskConfig

from .agent_factory import create_agent
from .callbacks import WebUICallbacks
from models.messages import ConnectionStatus, ChatMessage, CompleteMessage

logger = logging.getLogger(__name__)


class ChatSession:
    """
    Manages a single chat session with its own agent and task loop.
    
    The task loop runs in a separate thread to maintain conversation
    context while allowing async WebSocket operations.
    """
    
    def __init__(self, session_id: str, websocket: WebSocket):
        self.session_id = session_id
        self.websocket = websocket
        self.running = False
        
        # Create agent and callbacks
        self.agent = create_agent(name=f"Assistant-{session_id[:8]}")
        self.callbacks = WebUICallbacks(self.agent, websocket)
        
        # Task management
        self.task: Optional[Task] = None
        self.task_thread: Optional[threading.Thread] = None
        
        logger.info(f"Created chat session: {session_id}")
        
    async def start(self):
        """Start the chat session and task loop."""
        self.running = True
        
        # Send connection status
        await self._send_connection_status()
        
        # Send welcome message
        await self.callbacks.send_system_message(
            "Welcome! I'm ready to chat. Type a message to begin our conversation."
        )
        
        # Create and start the task
        self._start_task_loop()
        
    def _start_task_loop(self):
        """Start the Langroid task loop in a separate thread."""
        # Create task with interactive mode
        self.task = Task(
            self.agent,
            name=f"ChatTask-{self.session_id[:8]}",
            interactive=True,  # Maintains conversation loop
            config=TaskConfig(
                addressing_prefix="",  # No prefix in messages
                show_subtask_response=True,
                max_cost=10.0,  # Reasonable limit
                max_tokens=100000,  # Reasonable limit
            )
        )
        
        # Run task in thread
        def run_task():
            try:
                logger.info(f"Starting task loop for session {self.session_id}")
                result = self.task.run()
                logger.info(f"Task loop completed for session {self.session_id}: {result}")
            except Exception as e:
                logger.error(f"Task error in session {self.session_id}: {e}")
                import traceback
                traceback.print_exc()
            finally:
                self.running = False
                
        self.task_thread = threading.Thread(
            target=run_task,
            name=f"TaskThread-{self.session_id[:8]}",
            daemon=True
        )
        self.task_thread.start()
        
    async def handle_message(self, data: Dict[str, Any]):
        """
        Handle incoming WebSocket message.
        
        Args:
            data: Message data from WebSocket
        """
        try:
            msg_type = data.get("type")
            
            if msg_type == "message":
                # User message - pass to agent via callbacks
                content = data.get("content", "")
                if content:
                    logger.info(f"Session {self.session_id} received: {content[:50]}...")
                    
                    # Pass to agent callbacks (frontend already displays user messages)
                    self.callbacks.handle_user_message(content)
                    
            elif msg_type == "command":
                # Handle system commands
                await self._handle_command(data)
                
        except Exception as e:
            logger.error(f"Error handling message in session {self.session_id}: {e}")
            await self.callbacks.send_system_message(f"Error: {str(e)}")
            
    async def _echo_user_message(self, content: str):
        """Echo user message back to UI for display."""
        message = CompleteMessage(
            message=ChatMessage(
                id=str(uuid4()),
                content=content,
                sender="user"
            )
        )
        await self.websocket.send_json(message.dict())
        
    async def _handle_command(self, data: Dict[str, Any]):
        """Handle system commands."""
        command = data.get("command")
        
        if command == "stop":
            await self.stop()
        elif command == "clear":
            # Clear chat history
            self.agent.clear_history()
            await self.callbacks.send_system_message("Chat history cleared.")
        elif command == "reset":
            # Reset the entire session
            await self.stop()
            await self.start()
        else:
            await self.callbacks.send_system_message(f"Unknown command: {command}")
            
    async def _send_connection_status(self):
        """Send initial connection status."""
        status = ConnectionStatus(
            status="connected",
            session_id=self.session_id,
            message=f"Connected to Langroid Chat Backend"
        )
        await self.websocket.send_json(status.dict())
        
    async def stop(self):
        """Stop the chat session gracefully."""
        self.running = False
        
        # If waiting for user input, send 'q' to terminate the interactive task
        if self.callbacks and self.callbacks.waiting_for_user:
            self.callbacks.handle_user_message('q')
            
        # Wait briefly for thread to finish
        if self.task_thread and self.task_thread.is_alive():
            self.task_thread.join(timeout=2.0)
            
        logger.info(f"Stopped chat session: {self.session_id}")
        

class SessionManager:
    """
    Manages multiple chat sessions.
    """
    
    def __init__(self):
        self.sessions: Dict[str, ChatSession] = {}
        self._lock = asyncio.Lock()
        logger.info("Session manager initialized")
        
    async def create_session(self, websocket: WebSocket) -> str:
        """Create a new chat session."""
        session_id = f"session_{uuid4().hex}"
        
        async with self._lock:
            session = ChatSession(session_id, websocket)
            self.sessions[session_id] = session
            
        await session.start()
        
        logger.info(f"Created and started session: {session_id}")
        return session_id
        
    async def handle_message(self, session_id: str, data: Dict[str, Any]):
        """Route message to appropriate session."""
        session = self.sessions.get(session_id)
        if session:
            await session.handle_message(data)
        else:
            logger.warning(f"Message for unknown session: {session_id}")
            
    async def close_session(self, session_id: str):
        """Close and clean up a session."""
        async with self._lock:
            session = self.sessions.get(session_id)
            if session:
                await session.stop()
                del self.sessions[session_id]
                logger.info(f"Closed session: {session_id}")
                
    def get_active_sessions(self) -> int:
        """Get count of active sessions."""
        return len(self.sessions)
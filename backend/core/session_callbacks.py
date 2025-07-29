"""
Session management using the WebSocket callbacks approach.
"""
import asyncio
import logging
import queue
import threading
from typing import Dict, Optional, Any
from uuid import uuid4

from fastapi import WebSocket
import langroid as lr
from langroid.agent.chat_agent import ChatAgent
from langroid.agent.task import Task

from .websocket_callbacks import create_websocket_callbacks, WebSocketCallbacks
# from .streaming_agent import StreamingChatAgent, create_streaming_agent
from models.messages import ConnectionStatus

logger = logging.getLogger(__name__)


class CallbackChatSession:
    """
    Chat session using the native callback approach.
    """
    
    def __init__(self, session_id: str, websocket: WebSocket):
        self.session_id = session_id
        self.websocket = websocket
        self.agent: Optional[ChatAgent] = None
        self.task: Optional[Task] = None
        self.callbacks: Optional[WebSocketCallbacks] = None
        
        # Queues for communication
        self.outgoing_queue = asyncio.Queue()
        self.user_input_queue = queue.Queue()
        
        # State
        self._running = False
        self._task_thread: Optional[threading.Thread] = None
        self._processor_task: Optional[asyncio.Task] = None
        
        logger.info(f"CallbackChatSession created: {session_id}")
        
    async def initialize(self, agent: ChatAgent):
        """Initialize the session with an agent."""
        self.agent = agent
        
        # Create callbacks
        self.callbacks = create_websocket_callbacks(
            session_id=self.session_id,
            websocket=self.websocket,
            message_queue=self.outgoing_queue,
            user_input_queue=self.user_input_queue
        )
        
        # Attach callbacks to agent
        self.callbacks.attach_to_agent(agent)
        
        # Create task with interactive mode
        self.task = Task(
            agent,
            name=f"ChatTask-{self.session_id}",
            interactive=True
        )
        
        # Update task responders to ensure callbacks are used
        self.callbacks.update_task_responders(self.task)
        
        logger.info(f"Session initialized with agent: {agent.config.name}")
        
    async def start(self, send_greeting: bool = True):
        """Start the chat session.
        
        Args:
            send_greeting: Whether to send initial greeting (False for reused sessions)
        """
        self._running = True
        
        # Send connection status
        connection_status = ConnectionStatus(
            type="connection",
            status="connected", 
            session_id=self.session_id,
            message="Chat session started"
        )
        await self._send_message(connection_status.dict())
        
        # Start message processor
        self._processor_task = asyncio.create_task(self._process_outgoing_messages())
        
        if send_greeting and (not self._task_thread or not self._task_thread.is_alive()):
            # Delay task start to ensure WebSocket is stable
            await asyncio.sleep(0.1)
            
            # Start task in thread
            self._task_thread = threading.Thread(
                target=self._run_task,
                name=f"Task-{self.session_id}"
            )
            self._task_thread.start()
        # else: Reusing existing session, task is already running
        
        logger.info(f"Session {self.session_id} started (send_greeting={send_greeting})")
        
    def _run_task(self):
        """Run the Langroid task in a thread."""
        logger.info(f"🚀 Starting task.run() for session {self.session_id}")
        try:
            # Run task without initial message - let the agent send its own greeting
            result = self.task.run()
            logger.info(f"✅ Task completed with result: {result}")
        except Exception as e:
            logger.error(f"❌ Task error in session {self.session_id}: {e}", exc_info=True)
        finally:
            self._running = False
            logger.info(f"🏁 Task thread finished for session {self.session_id}")
            
    async def _process_outgoing_messages(self):
        """Process messages from the outgoing queue."""
        logger.info(f"Started _process_outgoing_messages for session {self.session_id}")
        while self._running:
            try:
                # Get message with timeout to allow checking _running
                message = await asyncio.wait_for(
                    self.outgoing_queue.get(),
                    timeout=1.0
                )
                await self._send_message(message)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"Error processing outgoing message: {e}", exc_info=True)
                # Don't crash on WebSocket errors, just continue
                if "WebSocket" in str(e):
                    continue
        logger.info(f"Stopped _process_outgoing_messages for session {self.session_id}")
                
    async def _send_message(self, message: Any):
        """Send a message via WebSocket."""
        try:
            # Check if WebSocket is connected
            if hasattr(self.websocket, 'client_state') and self.websocket.client_state.name != 'CONNECTED':
                logger.warning(f"WebSocket not connected, skipping message: {message}")
                return
                
            if isinstance(message, dict):
                await self.websocket.send_json(message)
            else:
                await self.websocket.send_json(message.model_dump())
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            # Mark session as not running if WebSocket fails
            if "WebSocket" in str(e) or "not connected" in str(e).lower():
                self._running = False
                
            
    async def handle_message(self, data: dict):
        """Handle incoming WebSocket message."""
        msg_type = data.get("type")
        
        if msg_type == "user_input" or msg_type == "message":
            # Put user input in queue for agent
            content = data.get("content", "")
            logger.info(f"🟡 Received message type: {msg_type}, content: {content[:50]}...")
            logger.info(f"🟡 Queue object: {id(self.user_input_queue)}")
            self.user_input_queue.put(content)
            logger.info(f"🟢 Successfully queued user input!")
            
        elif msg_type == "ping":
            # Respond to ping
            await self._send_message({"type": "pong"})
            
        else:
            logger.warning(f"Unknown message type: {msg_type}")
            
    async def stop(self):
        """Stop the session and clean up resources."""
        logger.info(f"Stopping session {self.session_id}")
        self._running = False
        
        # Stop task thread
        if self._task_thread and self._task_thread.is_alive():
            # Put empty message to unblock user input
            self.user_input_queue.put("")
            self._task_thread.join(timeout=5)
            
        # Cancel processor task
        if self._processor_task:
            self._processor_task.cancel()
            try:
                await self._processor_task
            except asyncio.CancelledError:
                pass
                
        # Detach callbacks
        if self.callbacks and self.agent:
            self.callbacks.detach_from_agent(self.agent)
            
        logger.info(f"Session {self.session_id} stopped")


class CallbackSessionManager:
    """
    Manager for callback-based chat sessions.
    """
    
    def __init__(self):
        self.sessions: Dict[str, CallbackChatSession] = {}
        self.browser_sessions: Dict[str, str] = {}  # browser_session_id -> session_id
        self._lock = asyncio.Lock()
        logger.info("CallbackSessionManager initialized")
        
    async def create_or_get_session(self, websocket: WebSocket, browser_session_id: Optional[str] = None) -> tuple[CallbackChatSession, bool]:
        """Create a new chat session or get existing one for browser session.
        
        Returns:
            Tuple of (session, is_new) where is_new indicates if this is a new session
        """
        async with self._lock:
            # Check if we have an existing session for this browser
            if browser_session_id and browser_session_id in self.browser_sessions:
                existing_session_id = self.browser_sessions[browser_session_id]
                if existing_session_id in self.sessions:
                    # Reuse existing session but update websocket for new connection
                    session = self.sessions[existing_session_id]
                    # Update the websocket to the new connection
                    old_websocket = session.websocket
                    session.websocket = websocket
                    
                    # Update the outgoing queue in callbacks to use new websocket
                    if session.callbacks:
                        session.callbacks.websocket = websocket
                        
                    logger.info(f"Reusing session {existing_session_id} for browser {browser_session_id} - updated WebSocket")
                    
                    # Don't start a new task - the existing one is already running
                    return session, False
            
            # Create new session only if no existing session found
            session_id = str(uuid4())
            session = CallbackChatSession(session_id, websocket)
            self.sessions[session_id] = session
            
            # Track browser session if provided
            if browser_session_id:
                self.browser_sessions[browser_session_id] = session_id
                
        logger.info(f"Created new session: {session_id} for browser {browser_session_id}")
        return session, True
        
    async def create_session(self, websocket: WebSocket) -> CallbackChatSession:
        """Create a new chat session (backward compatibility)."""
        session, _ = await self.create_or_get_session(websocket)
        return session
        
    async def get_session(self, session_id: str) -> Optional[CallbackChatSession]:
        """Get a session by ID."""
        return self.sessions.get(session_id)
        
    async def remove_session(self, session_id: str):
        """Remove and stop a session."""
        async with self._lock:
            session = self.sessions.pop(session_id, None)
            
            # Also remove browser session mapping
            browser_session_id = None
            for browser_id, sess_id in list(self.browser_sessions.items()):
                if sess_id == session_id:
                    browser_session_id = browser_id
                    del self.browser_sessions[browser_id]
                    break
            
        if session:
            await session.stop()
            logger.info(f"Removed session: {session_id} (browser: {browser_session_id})")
            
    async def cleanup_all(self):
        """Stop and remove all sessions."""
        logger.info("Cleaning up all sessions")
        
        async with self._lock:
            session_ids = list(self.sessions.keys())
            
        for session_id in session_ids:
            await self.remove_session(session_id)
            
        logger.info("All sessions cleaned up")
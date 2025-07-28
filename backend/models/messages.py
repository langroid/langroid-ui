"""
Message models for WebSocket communication between frontend and backend.
"""
from typing import Optional, Literal, Union
from datetime import datetime
from pydantic import BaseModel, Field


# Client → Server Messages

class UserMessage(BaseModel):
    """User sends a chat message"""
    type: Literal["message"] = "message"
    content: str
    message_id: Optional[str] = None


class SystemCommand(BaseModel):
    """User sends a system command"""
    type: Literal["command"] = "command"
    command: Literal["stop", "reset", "clear"]
    

# Server → Client Messages

class StreamStart(BaseModel):
    """Indicates start of streaming response"""
    type: Literal["stream_start"] = "stream_start"
    message_id: str
    sender: Literal["assistant"] = "assistant"
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


class StreamToken(BaseModel):
    """Single token in a streaming response"""
    type: Literal["stream_token"] = "stream_token"
    message_id: str
    token: str


class StreamEnd(BaseModel):
    """Indicates end of streaming response"""
    type: Literal["stream_end"] = "stream_end"
    message_id: str


class ChatMessage(BaseModel):
    """Complete chat message"""
    id: str
    content: str
    sender: Literal["user", "assistant", "system"]
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


class CompleteMessage(BaseModel):
    """Complete message (non-streaming)"""
    type: Literal["message"] = "message"
    message: ChatMessage


class InputRequest(BaseModel):
    """Request user input with optional prompt"""
    type: Literal["input_request"] = "input_request"
    prompt: Optional[str] = None
    timeout: Optional[int] = 300  # seconds


class ErrorMessage(BaseModel):
    """Error message"""
    type: Literal["error"] = "error"
    error: str
    details: Optional[str] = None


class ConnectionStatus(BaseModel):
    """Connection status update"""
    type: Literal["connection"] = "connection"
    status: Literal["connected", "disconnected", "reconnecting"]
    session_id: Optional[str] = None
    message: Optional[str] = None


class ToolCall(BaseModel):
    """Tool usage notification"""
    type: Literal["tool_call"] = "tool_call"
    tool_name: str
    tool_args: Optional[dict] = None
    message_id: str


class ToolResult(BaseModel):
    """Tool execution result"""
    type: Literal["tool_result"] = "tool_result"
    tool_name: str
    result: str
    message_id: str


# Union types for easy handling
ClientMessage = Union[UserMessage, SystemCommand]
ServerMessage = Union[
    StreamStart, 
    StreamToken, 
    StreamEnd,
    CompleteMessage, 
    InputRequest, 
    ErrorMessage, 
    ConnectionStatus,
    ToolCall,
    ToolResult
]
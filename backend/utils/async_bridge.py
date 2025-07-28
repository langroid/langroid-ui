"""
Thread-safe utilities for bridging sync and async code.
"""
import asyncio
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def queue_message_threadsafe(
    message: Dict[str, Any], 
    queue: asyncio.Queue, 
    loop: asyncio.AbstractEventLoop
) -> None:
    """
    Queue a message from any thread to an async queue.
    
    This is used to send messages from sync callback methods
    (running in threads) to the async WebSocket handler.
    
    Args:
        message: The message dictionary to queue
        queue: The asyncio.Queue to put the message in
        loop: The event loop where the queue lives
    """
    try:
        # Check if we're already in the target loop
        current_loop = asyncio.get_event_loop()
        if current_loop == loop and loop.is_running():
            # We're in the right loop, just create a task
            asyncio.create_task(queue.put(message))
        else:
            # We're in a different thread/loop, use thread-safe method
            asyncio.run_coroutine_threadsafe(
                queue.put(message),
                loop
            )
    except RuntimeError:
        # We're in a thread without an event loop
        # This is expected when called from the task thread
        asyncio.run_coroutine_threadsafe(
            queue.put(message),
            loop
        )
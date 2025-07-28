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
    logger.info(f"🔄 queue_message_threadsafe called: type={message.get('type')}")
    try:
        # Check if we're already in the target loop
        current_loop = asyncio.get_event_loop()
        logger.info(f"🔄 Current loop: {id(current_loop)}, Target loop: {id(loop)}, Loop running: {loop.is_running()}")
        
        if current_loop == loop and loop.is_running():
            # We're in the right loop, just create a task
            logger.info("🔄 Using asyncio.create_task (same loop)")
            task = asyncio.create_task(queue.put(message))
            logger.info(f"🔄 Task created: {task}")
        else:
            # We're in a different thread/loop, use thread-safe method
            logger.info("🔄 Using run_coroutine_threadsafe (different loop/thread)")
            future = asyncio.run_coroutine_threadsafe(
                queue.put(message),
                loop
            )
            logger.info(f"🔄 Future created: {future}")
    
    except RuntimeError as e:
        # We're in a thread without an event loop
        # This is expected when called from the task thread
        logger.info(f"🔄 RuntimeError (expected from thread): {e}")
        logger.info("🔄 Using run_coroutine_threadsafe (no current loop)")
        future = asyncio.run_coroutine_threadsafe(
            queue.put(message),
            loop
        )
        logger.info(f"🔄 Future created from thread: {future}")
    except Exception as e:
        logger.error(f"❌ Unexpected error in queue_message_threadsafe: {e}")
        import traceback
        traceback.print_exc()
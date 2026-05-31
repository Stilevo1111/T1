"""Event-driven architecture for loose coupling"""
from __future__ import annotations
import asyncio
import logging
from typing import Callable, Any, Dict, List
from collections import defaultdict

logger = logging.getLogger(__name__)


class EventBus:
    """Simple in-memory event bus"""
    
    def __init__(self):
        self._handlers: Dict[str, List[Callable]] = defaultdict(list)
    
    def on(self, event: str) -> Callable:
        """Decorator to register event handler"""
        def decorator(handler: Callable) -> Callable:
            self._handlers[event].append(handler)
            logger.debug(f"Registered handler for event: {event}")
            return handler
        return decorator
    
    async def emit(self, event: str, data: Any = None):
        """Emit event to all handlers"""
        handlers = self._handlers.get(event, [])
        if not handlers:
            return
        
        tasks = [handler(data) for handler in handlers]
        await asyncio.gather(*tasks, return_exceptions=True)


# Global event bus instance
event_bus = EventBus()


# Pre-defined events
@event_bus.on("user.updated")
async def handle_user_update(data: dict):
    """Handle user update event"""
    logger.info("user_updated", user_id=data.get("user_id"), changes=data.get("changes"))


@event_bus.on("fissure.rolled")
async def handle_fissure_roll(data: dict):
    """Handle fissure roll event"""
    logger.info("fissure_rolled", user_id=data.get("user_id"), result=data.get("result"))
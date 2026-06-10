"""
backend/services/ws_broadcast.py
=================================
Manages WebSocket connections and GPS broadcast pipeline.

Architecture:
  1. Parent connects via WS: /ws/track/{tracking_code}?token=JWT
  2. Server validates token and tracking code
  3. Server subscribes to Redis channel: tracking:{code}:gps
  4. When GPS message arrives on channel, broadcast to all connected parents
  5. On disconnect, clean up subscription and parent count

Connection Registry:
  Dict[tracking_code, Set[WebSocket]] — tracks active connections per session

Redis Pub/Sub:
  - Agent 2 publishes: tracking:{code}:gps
  - This module subscribes and relays to WebSocket clients
"""

import asyncio
import json
import logging
import time
from collections import defaultdict
from typing import Set

from fastapi import WebSocket
import redis.asyncio as aioredis

log = logging.getLogger("bustrack.ws")


class TrackingBroadcaster:
    """
    Manages all WebSocket connections for live GPS tracking.
    
    One instance per FastAPI app. Handles:
    - Connection registry (tracking_code -> set of WebSockets)
    - Redis pub/sub subscription per tracking code
    - Broadcasting GPS updates to connected parents
    - Heartbeat ping/pong
    - Graceful cleanup on disconnect
    """

    def __init__(self, redis: aioredis.Redis):
        self._redis = redis
        # tracking_code -> set of WebSocket connections
        self._connections: dict[str, Set[WebSocket]] = defaultdict(set)
        # tracking_code -> asyncio.Task (pubsub listener)
        self._listeners: dict[str, asyncio.Task] = {}
        # WebSocket -> tracking_code (reverse lookup for cleanup)
        self._ws_to_code: dict[WebSocket, str] = {}
        # WebSocket -> last activity timestamp
        self._last_activity: dict[WebSocket, float] = {}

    @property
    def connection_count(self) -> int:
        return sum(len(v) for v in self._connections.values())

    def get_parent_count(self, tracking_code: str) -> int:
        return len(self._connections.get(tracking_code, set()))

    async def register(self, tracking_code: str, ws: WebSocket) -> None:
        """Register a new WebSocket connection for a tracking session."""
        self._connections[tracking_code].add(ws)
        self._ws_to_code[ws] = tracking_code
        self._last_activity[ws] = time.time()

        # Start Redis listener for this code if not already running
        if tracking_code not in self._listeners:
            task = asyncio.create_task(
                self._listen_redis(tracking_code),
                name=f"ws-listener-{tracking_code}",
            )
            self._listeners[tracking_code] = task
            log.info("Started Redis listener for tracking:%s", tracking_code)

        # Update parent count in Redis
        await self._redis.sadd(
            f"tracking:{tracking_code}:parents",
            f"ws_{id(ws)}",
        )

        # Notify all connected clients about new parent count
        count = self.get_parent_count(tracking_code)
        await self._broadcast(tracking_code, {
            "type": "parents_count",
            "count": count,
        })

        log.info(
            "WS registered: code=%s total=%d",
            tracking_code, count,
        )

    async def unregister(self, ws: WebSocket) -> None:
        """Remove a WebSocket connection and clean up."""
        code = self._ws_to_code.pop(ws, None)
        self._last_activity.pop(ws, None)
        if code is None:
            return

        self._connections[code].discard(ws)

        # Remove from Redis parent set
        await self._redis.srem(f"tracking:{code}:parents", f"ws_{id(ws)}")

        # If no more connections for this code, stop the listener
        if not self._connections[code]:
            del self._connections[code]
            task = self._listeners.pop(code, None)
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                log.info("Stopped Redis listener for tracking:%s", code)
        else:
            # Notify remaining clients about updated parent count
            count = self.get_parent_count(code)
            await self._broadcast(code, {
                "type": "parents_count",
                "count": count,
            })

        log.info("WS unregistered: code=%s remaining=%d",
                 code, len(self._connections.get(code, set())))

    async def _listen_redis(self, tracking_code: str) -> None:
        """
        Subscribe to Redis channel and relay messages to WebSocket clients.
        
        This runs as a long-lived asyncio task, one per tracking_code.
        When the last client disconnects, the task is cancelled.
        """
        channel_name = f"tracking:{tracking_code}:gps"
        pubsub = self._redis.pubsub()

        try:
            await pubsub.subscribe(channel_name)
            log.info("Subscribed to Redis channel: %s", channel_name)

            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue

                try:
                    data = message["data"]
                    if isinstance(data, bytes):
                        data = data.decode("utf-8")
                    
                    # Parse and broadcast
                    parsed = json.loads(data)
                    await self._broadcast(tracking_code, parsed)
                except (json.JSONDecodeError, Exception) as exc:
                    log.debug("Failed to parse/broadcast GPS: %s", exc)

        except asyncio.CancelledError:
            log.info("Redis listener cancelled: %s", channel_name)
        except Exception as exc:
            log.error("Redis listener error: %s: %s", channel_name, exc)
        finally:
            try:
                await pubsub.unsubscribe(channel_name)
                await pubsub.close()
            except Exception:
                pass

    async def _broadcast(self, tracking_code: str, data: dict) -> None:
        """Send a message to all connected WebSocket clients for a tracking code."""
        clients = self._connections.get(tracking_code, set()).copy()
        if not clients:
            return

        payload = json.dumps(data)
        dead = []

        for ws in clients:
            try:
                await ws.send_text(payload)
                self._last_activity[ws] = time.time()
            except Exception:
                dead.append(ws)

        # Clean up dead connections
        for ws in dead:
            await self.unregister(ws)

    async def send_to_session(self, tracking_code: str, data: dict) -> None:
        """Send a specific message to all clients in a tracking session."""
        await self._broadcast(tracking_code, data)

    async def handle_heartbeat(self, ws: WebSocket) -> None:
        """Handle incoming ping from client, respond with pong."""
        try:
            await ws.send_text("pong")
        except Exception:
            pass

    async def check_stale_connections(self, max_idle_seconds: int = 120) -> int:
        """
        Check for and remove stale WebSocket connections.
        Call this periodically (e.g., every 30 seconds).
        Returns number of stale connections removed.
        """
        now = time.time()
        stale = []
        
        for ws, last in self._last_activity.items():
            if now - last > max_idle_seconds:
                stale.append(ws)

        for ws in stale:
            try:
                await ws.close(code=4000, reason="Idle timeout")
            except Exception:
                pass
            await self.unregister(ws)

        if stale:
            log.info("Removed %d stale connections", len(stale))
        return len(stale)

    async def shutdown(self) -> None:
        """Gracefully close all connections and listeners."""
        # Cancel all listeners
        for task in self._listeners.values():
            task.cancel()
        
        # Close all WebSocket connections
        for clients in self._connections.values():
            for ws in clients:
                try:
                    await ws.close(code=1001, reason="Server shutting down")
                except Exception:
                    pass

        self._connections.clear()
        self._listeners.clear()
        self._ws_to_code.clear()
        self._last_activity.clear()
        log.info("Broadcaster shutdown complete")

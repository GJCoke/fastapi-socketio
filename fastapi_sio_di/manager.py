"""Cross-instance call manager using Redis List + BLPOP."""
import asyncio

import msgpack
from socketio import AsyncRedisManager

from .exceptions import CallError


class AsyncRedisCallManager(AsyncRedisManager):
    """Redis manager that supports cross-instance call() via BLPOP.

    Usage::

        sio = AsyncServer(
            client_manager=AsyncRedisCallManager('redis://localhost:6379/0')
        )
    """

    name = 'aioredis-call'

    def __init__(self, url='redis://localhost:6379/0', channel='socketio',
                 write_only=False, logger=None, json=None, redis_options=None):
        super().__init__(url=url, channel=channel, write_only=write_only,
                         logger=logger, json=json, redis_options=redis_options)
        self._call_counter = 0

    def _generate_call_id(self) -> str:
        """Generate a unique call ID: {host_id}:{counter}."""
        self._call_counter += 1
        return f"{self.host_id}:{self._call_counter}"

    def _pack_result(self, status: str, *, data=None, code=None, message=None) -> bytes:
        """Serialize a call result to msgpack bytes for RPUSH."""
        if status == "ok":
            payload = {"status": "ok", "data": list(data) if data else []}
        else:
            payload = {"status": "error", "code": code, "message": message}
        return msgpack.packb(payload, use_bin_type=True)

    def _unpack_result(self, raw: bytes):
        """Deserialize a call result from msgpack bytes.

        Returns the ACK args as a tuple, or raises CallError on error.
        """
        result = msgpack.unpackb(raw, raw=False)
        if result["status"] == "error":
            raise CallError(result["code"], result["message"])
        data = result["data"]
        if not data:
            return None
        if len(data) == 1:
            return data[0]
        return tuple(data)

    async def _emit_with_call_id(self, event: str, data, namespace: str,
                                  room: str, call_id: str, timeout: int):
        """Publish a call_emit message to the pub/sub channel."""
        if isinstance(data, tuple):
            data = list(data)
        elif not isinstance(data, list):
            data = [data]
        message = {
            'method': 'call_emit',
            'event': event,
            'data': data,
            'namespace': namespace,
            'room': room,
            'call_id': call_id,
            'timeout': timeout,
            'host_id': self.host_id,
        }
        await self.redis.publish(self.channel, self.json.dumps(message))

    async def _handle_call_emit(self, message):
        """Handle a call_emit message from another instance.

        If the target sid is connected locally, emit the event and register
        a callback that writes the ACK result to Redis.
        """
        room = message['room']
        namespace = message.get('namespace', '/')

        if not self.is_connected(room, namespace):
            return

        call_id = message['call_id']
        timeout = message['timeout']
        event = message['event']
        data = message['data']

        # Unwrap data list
        if isinstance(data, list):
            if len(data) == 1:
                data = data[0]
            else:
                data = tuple(data)

        async def redis_callback(*args):
            key = f"sio:call:{call_id}"
            payload = self._pack_result("ok", data=args)
            await self.redis.rpush(key, payload)
            await self.redis.expire(key, timeout + 5)

        await self._local_emit(event, data, namespace=namespace,
                               room=room, callback=redis_callback)

    async def _local_emit(self, event, data, namespace=None, room=None,
                          skip_sid=None, callback=None):
        """Emit directly to local clients, bypassing pub/sub broadcast."""
        from socketio.async_manager import AsyncManager
        await AsyncManager.emit(self, event, data, namespace=namespace,
                                room=room, skip_sid=skip_sid, callback=callback)

    async def _thread(self):
        """Override parent _thread to handle call_emit messages."""
        while True:
            try:
                async for message in self._listen():
                    data = None
                    if isinstance(message, dict):
                        data = message
                    else:
                        try:
                            data = self.json.loads(message)
                        except Exception:
                            pass
                    if data and 'method' in data:
                        self._get_logger().debug(
                            'pubsub message: {}'.format(data['method']))
                        try:
                            if data['method'] == 'call_emit':
                                await self._handle_call_emit(data)
                            elif data['method'] == 'callback':
                                await self._handle_callback(data)
                            elif data.get('host_id') != self.host_id:
                                if data['method'] == 'emit':
                                    await self._handle_emit(data)
                                elif data['method'] == 'disconnect':
                                    await self._handle_disconnect(data)
                                elif data['method'] == 'enter_room':
                                    await self._handle_enter_room(data)
                                elif data['method'] == 'leave_room':
                                    await self._handle_leave_room(data)
                                elif data['method'] == 'close_room':
                                    await self._handle_close_room(data)
                        except asyncio.CancelledError:
                            raise
                        except Exception:
                            self.server.logger.exception(
                                'Handler error in pubsub listening thread')
                self.server.logger.error('pubsub listen() exited unexpectedly')
                break
            except asyncio.CancelledError:
                break
            except Exception:
                self.server.logger.exception(
                    'Unexpected Error in pubsub listening thread')

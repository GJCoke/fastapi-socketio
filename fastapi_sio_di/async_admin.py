from typing import Any, List
from socketio.async_admin import (
    InstrumentedAsyncServer as SocketIOInstrumentedAsyncServer,
)

from .params import SID, Environ


class InstrumentedAsyncServer(SocketIOInstrumentedAsyncServer):

    async def admin_connect(self, sid: SID, environ: Environ, client_auth: Any):
        return await super().admin_connect(sid=sid, environ=environ, client_auth=client_auth)

    async def admin_disconnect(self, sid: SID, namespace: str, close: bool, room_filter: List[str] = None):
        return await super().admin_disconnect(sid, namespace=namespace, close=close, room_filter=room_filter)
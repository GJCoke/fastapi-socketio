from typing import Any
from socketio.async_admin import (
    InstrumentedAsyncServer as SocketIOInstrumentedAsyncServer,
)

from .params import SID, Environ


class InstrumentedAsyncServer(SocketIOInstrumentedAsyncServer):

    async def admin_connect(self, sid: SID, environ: Environ, client_auth: Any):
        return await super().admin_connect(sid=sid, environ=environ, client_auth=client_auth)

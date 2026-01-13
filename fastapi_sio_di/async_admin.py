import time
from typing import Any, List

from socketio.async_admin import (
    InstrumentedAsyncServer as SocketIOInstrumentedAsyncServer,
    HOSTNAME,
    PID,
)

from .params import SID, Environ


class InstrumentedAsyncServer(SocketIOInstrumentedAsyncServer):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._stats_task_running = False

        # 当服务器初始化此类后就应该开始任务, 否则后台时间不准确, 且在分布式时存在问题
        self.stop_stats_event = self.sio.eio.create_event()
        self.stats_task = self.sio.start_background_task(self._emit_server_stats)

    async def admin_connect(self, sid: SID, environ: Environ, client_auth: Any):
        return await super().admin_connect(sid=sid, environ=environ, client_auth=client_auth)

    async def admin_disconnect(self, namespace, close, sid, room_filter=None):
        await self.sio.disconnect(sid=sid, namespace=namespace)

    async def _emit_server_stats(self):
        """重写统计信息推送逻辑，确保全局只有一个协程在跑"""
        if self._stats_task_running:
            return

        self._stats_task_running = True
        try:
            start_time = time.time()

            while not self.stop_stats_event.is_set():
                namespaces = list(self.sio.handlers.keys())
                namespaces.sort()

                await self.sio.sleep(self.server_stats_interval)

                await self.sio.emit(
                    "server_stats",
                    {
                        "serverId": self.server_id,
                        "hostname": HOSTNAME,
                        "pid": PID,
                        "uptime": time.time() - start_time,
                        "clientsCount": len(self.sio.eio.sockets),
                        "pollingClientsCount": len(
                            [s for s in self.sio.eio.sockets.values() if not s.upgraded]
                        ),
                        "aggregatedEvents": self.event_buffer.get_and_clear(),
                        "namespaces": [
                            {
                                "name": nsp,
                                "socketsCount": len(
                                    self.sio.manager.rooms.get(nsp, {None: []}).get(
                                        None, []
                                    )
                                ),
                            }
                            for nsp in namespaces
                        ],
                    },
                    namespace=self.admin_namespace,
                )

                while self.admin_queue:
                    event, args = self.admin_queue.pop(0)
                    await self.sio.emit(event, args, namespace=self.admin_namespace)
        finally:
            self._stats_task_running = False

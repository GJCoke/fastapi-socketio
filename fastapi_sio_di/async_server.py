import asyncio
from typing import Any, Awaitable, Callable, Optional, Union

from socketio import AsyncServer as SocketIOAsyncServer

from .base_server import BaseServer


class AsyncServer(BaseServer, SocketIOAsyncServer):
    async def emit(
        self,
        event: str,
        data: Optional[Any] = None,
        *,
        to: Optional[str] = None,
        room: Optional[str] = None,
        skip_sid: Optional[Union[str, list[str]]] = None,
        namespace: Optional[str] = None,
        callback: Optional[Callable] = None,
        ignore_queue: bool = False,
    ) -> Awaitable[None]:
        data = self._pydantic_model_to_dict(data)
        return await super().emit(
            event=event,
            data=data,
            to=to,
            room=room,
            skip_sid=skip_sid,
            namespace=namespace,
            callback=callback,
            ignore_queue=ignore_queue,
        )

    async def send(
        self,
        data: Any,
        *,
        to: Optional[str] = None,
        room: Optional[str] = None,
        skip_sid: Optional[Union[str, list[str]]] = None,
        namespace: Optional[str] = None,
        callback: Optional[Callable] = None,
        ignore_queue: bool = False,
    ) -> Awaitable[None]:
        return await self.emit(
            "message",
            data=data,
            to=to,
            room=room,
            skip_sid=skip_sid,
            namespace=namespace,
            callback=callback,
            ignore_queue=ignore_queue,
        )

    async def _trigger_event(
        self, event: str, namespace: str, *args: Any
    ) -> Optional[Awaitable[None]]:
        handler, args = self._get_event_handler(event, namespace, args)
        if handler:
            try:
                if asyncio.iscoroutinefunction(handler):
                    ret = await self._call_handler(handler, event, args)
                else:
                    ret = self._call_handler(handler, event, args)
            except asyncio.CancelledError:
                ret = None
            return ret

        handler, args = self._get_namespace_handler(namespace, args)
        if handler:
            return await handler.trigger_event(event, *args)

        else:
            return self.not_handled

    @staticmethod
    def _call_handler(
        handler: Callable, event: str, args: tuple
    ) -> Union[Callable, Awaitable[Callable]]:
        if event == "connect":
            sid = args[0]
            environ = args[1]
            auth = args[2] if len(args) > 2 else None
            return handler(sid, auth, environ=environ)
        else:
            return handler(*args)

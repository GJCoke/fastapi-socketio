from socketio import Server as SocketIOServer
from typing import Any, Optional, Union, List, Callable

from .base_server import BaseServer


class Server(BaseServer, SocketIOServer):
    def emit(
        self,
        event: str,
        data: Optional[Any] = None,
        *,
        to: Optional[str] = None,
        room: Optional[str] = None,
        skip_sid: Optional[Union[str, List[str]]] = None,
        namespace: Optional[str] = None,
        callback: Optional[Callable] = None,
        ignore_queue: bool = False,
    ) -> None:
        data = self._pydantic_model_to_dict(data)
        return super().emit(
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
        data: Optional[Any] = None,
        *,
        to: Optional[str] = None,
        room: Optional[str] = None,
        skip_sid: Optional[Union[str, List[str]]] = None,
        namespace: Optional[str] = None,
        callback: Optional[Callable] = None,
        ignore_queue: bool = False,
    ) -> None:
        return self.emit(
            event="message",
            data=data,
            to=to,
            room=room,
            skip_sid=skip_sid,
            namespace=namespace,
            callback=callback,
            ignore_queue=ignore_queue,
        )

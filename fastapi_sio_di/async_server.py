import asyncio
from functools import wraps
from typing import Any, Callable, Optional, Union, overload, TypeVar, Awaitable
from pydantic import BaseModel

from .dependencies import Dependant, LifespanContext, solve_dependant
from socketio import AsyncServer as SocketIOAsyncServer

T = TypeVar("T")

class AsyncServer(SocketIOAsyncServer):

    def __init__(
        self,
        cors_allowed_origins: Optional[Union[str, list[str]]] = None,
        serializer: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        if cors_allowed_origins is not None and "*" in cors_allowed_origins:
            cors_allowed_origins = "*"
        self.serializer = serializer
        super().__init__(cors_allowed_origins=cors_allowed_origins, **kwargs)

    def on(
        self,
        event: str,
        handler: Optional[Callable] = None,
        namespace: Optional[str] = None,
    ) -> Callable:
        def decorator(func: Callable) -> Callable:
            dependant = Dependant(func)

            @wraps(func)
            async def wrapper(sid: str, *args: Any, **kwargs: Any) -> None:
                context = LifespanContext()
                cache: dict[str, Any] = {}

                data = args[0] if args else None
                environ = kwargs.get("environ", {})

                cache["__sid__"] = sid
                cache["__data__"] = data
                cache["__environ__"] = environ

                try:
                    return await solve_dependant(dependant, context, cache)

                finally:
                    await context.run_teardowns()

            super().on(
                event=event, handler=wrapper, namespace=namespace
            )
            return func

        return decorator if handler is None else decorator(handler)

    @overload
    def _pydantic_model_to_dict(self, data: BaseModel) -> dict: ...

    @overload
    def _pydantic_model_to_dict(self, data: T) -> T: ...

    def _pydantic_model_to_dict(self, data: Union[BaseModel, T]) -> Union[dict, T]:
        if isinstance(data, BaseModel):
            serializer = self.serializer
            if serializer and hasattr(data, serializer):
                return getattr(data, serializer)()

            # 默认回退到 model_dump (Pydantic V2) 或 dict (Pydantic V1)
            if hasattr(data, "model_dump"):
                return data.model_dump()
            return data.dict()  # type: ignore
        return data

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

import asyncio
from functools import wraps
from typing import Any, Callable, Optional, Union, overload, TypeVar, Awaitable
from pydantic import BaseModel

from .dependencies import Dependant, LifespanContext, solve_dependant
from .params import Environ
from socketio import AsyncServer as SocketIOAsyncServer

T = TypeVar("T")


class AsyncServer(SocketIOAsyncServer):
    """
    Asynchronous Socket.IO server with Dependency Injection support.
    Extends python-socketio's AsyncServer to provide FastAPI-like dependency resolution
    for event handlers.
    """

    def __init__(
        self,
        cors_allowed_origins: Optional[Union[str, list[str]]] = None,
        serializer: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """
        Initialize the AsyncServer with optional CORS settings and serializer.

        :param cors_allowed_origins: List of allowed origins or '*' for all origins.
        :param serializer: Serializer method name for Pydantic models.
        :param kwargs: Additional keyword arguments for SocketIOAsyncServer.
        """
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
        """
        Register an event handler with dependency injection support.

        Allows using `Depends()` in the handler function parameters, similar to FastAPI.

        :param event: The event name (e.g., 'connect', 'message').
        :param handler: The function to handle the event. Acts as a decorator if None.
        :param namespace: The Socket.IO namespace.
        """

        def decorator(func: Callable) -> Callable:
            dependant = Dependant(func)

            @wraps(func)
            async def wrapper(sid: str, *args: Any, **kwargs: Any) -> None:
                context = LifespanContext()
                cache: dict[str, Any] = {}

                data = args[0] if args else None
                environ_raw = kwargs.get("environ", {})
                environ = Environ(environ_raw)

                cache["__sid__"] = sid
                cache["__data__"] = data
                cache["__environ__"] = environ

                try:
                    return await solve_dependant(dependant, context, cache)

                finally:
                    await context.run_teardowns()

            super(AsyncServer, self).on(
                event=event, handler=wrapper, namespace=namespace
            )
            return func

        return decorator if handler is None else decorator(handler)

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
        """
        Emit an event to one or more connected clients.
        Automatically serializes Pydantic models to dictionaries.

        :param event: The event name.
        :param data: The data to send. Can be a Pydantic model.
        :param to: Target recipient (Socket ID).
        :param room: Target room.
        :param skip_sid: Socket ID(s) to exclude.
        :param namespace: The namespace.
        :param callback: Function to call once client acknowledges.
        :param ignore_queue: If True, do not send to external message queue.
        """
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
        """Send a 'message' event to clients."""
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

    async def call(
        self,
        event: str,
        data: Optional[Any] = None,
        *,
        to: Optional[str] = None,
        sid: Optional[str] = None,
        namespace: Optional[str] = None,
        timeout: int = 60,
        ignore_queue: bool = False,
    ) -> Awaitable[None]:
        """Emit a custom event to a client and wait for the response."""
        return await super().call(
            event=event,
            data=data,
            to=to,
            sid=sid,
            namespace=namespace,
            timeout=timeout,
            ignore_queue=ignore_queue,
        )

    async def enter_room(
        self, sid: str, room: str, namespace: Optional[str] = None
    ) -> Awaitable[None]:
        """Add a client to a room."""
        return await super().enter_room(sid=sid, room=room, namespace=namespace)

    async def leave_room(
        self, sid: str, room: str, namespace: Optional[str] = None
    ) -> Awaitable[None]:
        """Remove a client from a room."""
        return await super().leave_room(sid=sid, room=room, namespace=namespace)

    async def close_room(
        self, room: str, namespace: Optional[str] = None
    ) -> Awaitable[None]:
        """Close a room."""
        return await super().close_room(room=room, namespace=namespace)

    async def disconnect(
        self, sid: str, namespace: Optional[str] = None, ignore_queue: bool = False
    ) -> Awaitable[None]:
        """Disconnect a client."""
        return await super().disconnect(
            sid=sid, namespace=namespace, ignore_queue=ignore_queue
        )

    async def sleep(self, seconds: int = 0) -> Awaitable[None]:
        """Sleep for a given number of seconds."""
        return await super().sleep(seconds=seconds)

    def instrument(self, auth=None, mode='development', read_only=False,
                   server_id=None, namespace='/admin',
                   server_stats_interval=2):
        """Instrument the Socket.IO server for monitoring with the `Socket.IO Admin UI <https://socket.io/docs/v4/admin-ui/>`_."""
        from .async_admin import InstrumentedAsyncServer
        return InstrumentedAsyncServer(self, auth=auth, mode=mode, read_only=read_only,
                                       server_id=server_id, namespace=namespace,
                                       server_stats_interval=server_stats_interval)

    async def _trigger_event(
        self,
        event: str,
        namespace: str,
        *args: Any,
    ) -> Optional[Awaitable[None]]:
        """Invoke an application event handler."""
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
        handler: Callable,
        event: str,
        args: tuple,
    ) -> Union[Callable, Awaitable[Callable]]:
        """Call an application event handler."""
        if event == "connect":
            sid = args[0]
            environ = args[1]
            auth = args[2] if len(args) > 2 else None
            return handler(sid, auth, environ=environ)
        elif event == "disconnect":
            return handler(*args[:-1])
        else:
            return handler(*args)

    @overload
    def _pydantic_model_to_dict(self, data: BaseModel) -> dict: ...

    @overload
    def _pydantic_model_to_dict(self, data: T) -> T: ...

    def _pydantic_model_to_dict(self, data: Union[BaseModel, T]) -> Union[dict, T]:
        """Convert a Pydantic model to a dictionary."""
        if isinstance(data, BaseModel):
            serializer = self.serializer
            if serializer and hasattr(data, serializer):
                return getattr(data, serializer)()

            # Default fallback to model_dump (Pydantic V2) or dict (Pydantic V1)
            if hasattr(data, "model_dump"):
                return data.model_dump()
            return data.dict()  # type: ignore
        return data

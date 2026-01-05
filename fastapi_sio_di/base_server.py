from socketio.base_server import BaseServer as SocketIOBaseServer
from functools import wraps
from typing import Any, Callable, Optional, Union, overload, TypeVar
from pydantic import BaseModel

from .dependencies import Dependant, LifespanContext, solve_dependant

T = TypeVar("T")


class BaseServer(SocketIOBaseServer):
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

            super(BaseServer, self).on(
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

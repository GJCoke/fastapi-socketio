import asyncio
import inspect
from contextlib import AsyncExitStack, asynccontextmanager
from functools import lru_cache
from typing import (
    Annotated,
    Any,
    Callable,
    Dict,
    Optional,
    Tuple,
    List,
    get_args,
    get_origin,
)

from pydantic import BaseModel, ValidationError
from fastapi.params import Depends
from .exceptions import SocketIOValidationError
from .params import SID, Environ
from .utils import get_param_depend


class LifespanContext:
    """Manages teardown functions for async/generator dependencies using AsyncExitStack.

    Guarantees:
    - All teardowns execute even if earlier ones raise
    - Handler exceptions propagate into generator yield points
    - LIFO teardown order
    """

    def __init__(self) -> None:
        self._stack = AsyncExitStack()

    async def __aenter__(self):
        await self._stack.__aenter__()
        return self

    async def __aexit__(self, *exc_info):
        return await self._stack.__aexit__(*exc_info)

    async def enter_async_context(self, cm):
        """Enter an async context manager; cleanup registered automatically."""
        return await self._stack.enter_async_context(cm)

    async def run_teardowns(self) -> None:
        """Backward-compatible teardown method. Closes the stack."""
        await self._stack.aclose()


class DependencySignature:
    """
    Caches the signature analysis of a function to avoid repeated inspection.
    """

    def __init__(self, func: Callable):
        self.sig = inspect.signature(func)
        self.params: Dict[str, Tuple[str, Any]] = {}

        # Analyze parameters once during initialization
        for name, param in self.sig.parameters.items():
            if dep := get_param_depend(param):
                # Handle Depends() with no argument: infer callable from annotation
                if dep.dependency is None:
                    annotation = param.annotation
                    if get_origin(annotation) is Annotated:
                        annotation = get_args(annotation)[0]
                    try:
                        if (
                            callable(annotation)
                            and annotation is not inspect.Parameter.empty
                        ):
                            inspect.signature(annotation)
                            dep = Depends(annotation, use_cache=dep.use_cache)
                        else:
                            self.params[name] = ("unknown", param)
                            continue
                    except (ValueError, TypeError):
                        self.params[name] = ("unknown", param)
                        continue
                self.params[name] = ("depend", dep)
            elif param.annotation in (SID, Environ):
                self.params[name] = ("special", param)
            elif param.default != inspect.Parameter.empty:
                self.params[name] = ("default", param.default)
            else:
                self.params[name] = ("unknown", param)


@lru_cache(maxsize=1024)
def get_signature_model(func: Callable) -> DependencySignature:
    """Cached factory for DependencySignature."""
    return DependencySignature(func)


class Dependant:
    """
    Static analysis container for the top-level event handler.
    Does roughly the same job as DependencySignature but is designed
    specifically for the main handler wrapper.
    """

    def __init__(self, call: Callable):
        self.call = call
        sig_model = get_signature_model(call)

        self.dependencies: Dict[str, Any] = {}
        self.special_params: Dict[str, Any] = {}
        self.unknown_params: List[Tuple[str, inspect.Parameter]] = []

        for name, (kind, value) in sig_model.params.items():
            if kind == "depend":
                self.dependencies[name] = value
            elif kind == "special":
                self.special_params[name] = value.annotation
            elif kind == "unknown":
                self.unknown_params.append((name, value))

    @property
    def data_param_name(self) -> Optional[str]:
        return self.unknown_params[0][0] if self.unknown_params else None


def resolve_special_param(param: inspect.Parameter, cache: Dict[str, Any]) -> Any:
    """Resolve special annotated parameters like SID or Environ."""

    if param.annotation is Environ:
        env_dict = cache.get("__environ__", {})
        return Environ(env_dict) if not isinstance(env_dict, Environ) else env_dict

    key = f"__{param.annotation.__name__.lower()}__"
    return cache.get(key)


def resolve_unknown_param(param: inspect.Parameter, cache: Dict[str, Any]) -> Any:
    """
    Resolve unknown parameters using type annotations and cache data.
    Automatically converts dict to Pydantic models if annotated.
    """
    annotation = param.annotation
    data = cache.get("__data__")

    # Check if the annotation is a Pydantic model class
    if inspect.isclass(annotation) and issubclass(annotation, BaseModel):
        # If data is already an instance, return it
        if isinstance(data, annotation):
            return data
        # If data is a dict, try to instantiate the model
        if isinstance(data, dict):
            try:
                return annotation(**data)
            except ValidationError as e:
                raise SocketIOValidationError(
                    errors=e.errors(), model_name=annotation.__name__
                ) from e

    return data


def _sync_next(gen):
    """Wrap next() to avoid StopIteration escaping into futures."""
    try:
        return (next(gen),)
    except StopIteration:
        return None


def _sync_throw(gen, exc):
    """Wrap generator.throw() to avoid StopIteration escaping into futures."""
    try:
        gen.throw(type(exc), exc, exc.__traceback__)
    except StopIteration:
        pass


async def run_with_lifespan_handling(
    func: Callable,
    kwargs: Dict[str, Any],
    context: LifespanContext,
) -> Any:
    """
    Run a function and register teardown via AsyncExitStack if it's a generator.
    """
    result = func(**kwargs)

    if inspect.isasyncgen(result):

        @asynccontextmanager
        async def _wrap():
            value = await result.__anext__()
            try:
                yield value
            except BaseException as exc:
                try:
                    await result.athrow(exc)
                except StopAsyncIteration:
                    pass
                raise
            else:
                try:
                    await result.__anext__()
                except StopAsyncIteration:
                    pass

        return await context.enter_async_context(_wrap())

    elif inspect.isgenerator(result):

        @asynccontextmanager
        async def _wrap():
            ret = await asyncio.to_thread(_sync_next, result)
            if ret is None:
                return
            value = ret[0]
            try:
                yield value
            except BaseException as exc:
                await asyncio.to_thread(_sync_throw, result, exc)
                raise
            else:
                await asyncio.to_thread(_sync_next, result)

        return await context.enter_async_context(_wrap())

    elif inspect.iscoroutine(result):
        return await result

    return result


async def extract_kwargs_from_signature(
    func: Callable,
    context: LifespanContext,
    cache: Dict[Any, Any],
    overrides: Optional[Dict[Callable, Callable]] = None,
) -> Dict[str, Any]:
    """
    Extract keyword arguments for SUB-DEPENDENCIES using cached signature analysis.
    """
    # Use cached signature model to avoid repeated inspect calls
    sig_model = get_signature_model(func)

    kwargs: Dict[str, Any] = {}
    unknown_params: List[Tuple[str, inspect.Parameter]] = []

    for name, (kind, value) in sig_model.params.items():
        if kind == "depend":
            # value is the dependency object (from get_param_depend)
            result = await solve_dependency(
                value.dependency,
                context,
                cache,
                value.use_cache,
                overrides=overrides,
            )
            kwargs[name] = result

        elif kind == "special":
            # value is the inspect.Parameter object
            kwargs[name] = resolve_special_param(value, cache)

        elif kind == "default":
            kwargs[name] = value

        elif kind == "unknown":
            # value is the inspect.Parameter object
            unknown_params.append((name, value))

    # Automatically infer data argument if unknown parameters exist
    if unknown_params:
        param_name, param = unknown_params[0]
        kwargs[param_name] = resolve_unknown_param(param, cache)

    return kwargs


async def solve_dependency(
    func: Callable,
    context: LifespanContext,
    cache: Dict[Any, Any],
    use_cache: bool = True,
    overrides: Optional[Dict[Callable, Callable]] = None,
) -> Any:
    """
    Resolve a dependency by recursively calling its own dependencies.
    """
    actual_func = overrides.get(func, func) if overrides else func

    if use_cache and actual_func in cache:
        return cache[actual_func]

    kwargs = await extract_kwargs_from_signature(
        actual_func,
        context,
        cache,
        overrides=overrides,
    )

    result = await run_with_lifespan_handling(actual_func, kwargs, context)

    if use_cache:
        cache[actual_func] = result

    return result


async def solve_dependant(
    dependant: Dependant,
    context: LifespanContext,
    cache: dict,
    overrides: Optional[Dict[Callable, Callable]] = None,
) -> Any:
    """
    Entry point for resolving the main event handler's dependencies.
    Uses the pre-calculated Dependant object for efficiency.
    """
    kwargs = {}

    # 1. Resolve special params (SID, Environ)
    for name, annotation in dependant.special_params.items():
        if annotation is Environ:
            kwargs[name] = cache.get("__environ__")
        else:
            key = f"__{annotation.__name__.lower()}__"
            kwargs[name] = cache.get(key)

    # 2. Resolve FastAPI dependencies
    for name, dep in dependant.dependencies.items():
        kwargs[name] = await solve_dependency(
            dep.dependency,
            context,
            cache,
            dep.use_cache,
            overrides=overrides,
        )

    # 3. Inject the main data payload
    raw_args = cache.get("__args__", ())

    for i, (name, param) in enumerate(dependant.unknown_params):
        if i < len(raw_args):
            val = raw_args[i]
            if (
                inspect.isclass(param.annotation)
                and issubclass(param.annotation, BaseModel)
                and isinstance(val, dict)
            ):
                try:
                    kwargs[name] = param.annotation(**val)
                except ValidationError as e:
                    raise SocketIOValidationError(
                        errors=e.errors(), model_name=param.annotation.__name__
                    ) from e
            else:
                kwargs[name] = val
        else:
            kwargs[name] = resolve_unknown_param(param, cache)

    return await run_with_lifespan_handling(dependant.call, kwargs, context)

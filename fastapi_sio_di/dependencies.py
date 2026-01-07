import inspect
from functools import lru_cache
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple, List

from pydantic import BaseModel
from .params import SID, Environ
from .utils import get_param_depend


class LifespanContext:
    """Manages teardown functions for async/generator dependencies."""

    def __init__(self) -> None:
        self.teardowns: List[Callable[[], Awaitable[None]]] = []

    async def run_teardowns(self) -> None:
        """Run all registered teardown callbacks in reverse order."""
        for cleanup in reversed(self.teardowns):
            await cleanup()


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
        self.data_param: Optional[inspect.Parameter] = None
        self.data_param_name: Optional[str] = None

        for name, (kind, value) in sig_model.params.items():
            if kind == "depend":
                self.dependencies[name] = value
            elif kind == "special":
                self.special_params[name] = value.annotation
            elif kind == "unknown":
                # Assume the first unknown parameter is the data payload
                if self.data_param is None:
                    self.data_param = value  # value is here inspect.Parameter
                    self.data_param_name = name


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
            return annotation(**data)

    return data


async def run_with_lifespan_handling(
    func: Callable,
    kwargs: Dict[str, Any],
    context: LifespanContext,
) -> Any:
    """
    Run a function and register teardown callbacks if it returns a generator.
    """
    result = func(**kwargs)

    if inspect.isasyncgen(result):
        value = await result.__anext__()

        async def cleanup() -> None:
            try:
                await result.__anext__()
            except StopAsyncIteration:
                pass

        context.teardowns.append(cleanup)
        return value

    elif inspect.isgenerator(result):
        value = next(result)

        async def cleanup() -> None:
            try:
                next(result)
            except StopIteration:
                pass

        context.teardowns.append(cleanup)
        return value

    elif inspect.iscoroutine(result):
        return await result

    return result


async def extract_kwargs_from_signature(
    func: Callable,
    context: LifespanContext,
    cache: Dict[Any, Any],
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
                value.dependency, context, cache, value.use_cache
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
) -> Any:
    """
    Resolve a dependency by recursively calling its own dependencies.
    """
    if use_cache and func in cache:
        return cache[func]

    kwargs = await extract_kwargs_from_signature(func, context, cache)

    result = await run_with_lifespan_handling(func, kwargs, context)

    if use_cache:
        cache[func] = result

    return result


async def solve_dependant(
    dependant: Dependant,
    context: LifespanContext,
    cache: dict,
) -> Any:
    """
    Entry point for resolving the main event handler's dependencies.
    Uses the pre-calculated Dependant object for efficiency.
    """
    kwargs = {}

    # 1. Resolve special params (SID, Environ)
    for name, annotation in dependant.special_params.items():
        key = f"__{annotation.__name__.lower()}__"
        kwargs[name] = cache.get(key)

    # 2. Resolve FastAPI dependencies
    for name, dep in dependant.dependencies.items():
        kwargs[name] = await solve_dependency(
            dep.dependency, context, cache, dep.use_cache
        )

    # 3. Inject the main data payload
    if dependant.data_param_name:
        kwargs[dependant.data_param_name] = resolve_unknown_param(
            dependant.data_param, cache
        )

    return await run_with_lifespan_handling(dependant.call, kwargs, context)

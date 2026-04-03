# fastapi-sio-di 依赖注入优化设计

> 日期: 2026-04-03
> 状态: 已批准
> 目标: 将 DI 引擎提升到生产级可靠性，对齐 FastAPI 的关键 DI 行为

---

## 背景

`fastapi-sio-di` 是一个将 FastAPI 风格的依赖注入引入 python-socketio 事件处理器的库。当前实现（v0.3.10）存在 8 个已识别问题，分为 P0（正确性）、P1（可测试性）、P2（健壮性）三个等级。

本设计基于对 FastAPI `dependencies/utils.py`、`dependencies/models.py`、`routing.py` 源码的逐行分析，选择性地对齐 FastAPI 的关键 DI 行为，同时保持库的轻量级定位。

---

## 问题清单

### P0 — 正确性和可靠性

| # | 问题 | 位置 | 影响 |
|---|------|------|------|
| 1 | Generator 依赖异常处理缺陷 | `dependencies.py:108-145` | `LifespanContext` 的 teardown 不传播异常到 generator；某个 teardown 抛异常时后续 teardown 不执行 |
| 2 | 同步函数阻塞事件循环 | `dependencies.py:116,131` | 同步 generator 的 `next()` 直接在事件循环调用，可能阻塞 |
| 3 | 无 Pydantic 验证错误处理 | `dependencies.py:97-103` | `annotation(**data)` 的 `ValidationError` 未被捕获，导致不可控的异常抛出 |

### P1 — 可测试性和开发体验

| # | 问题 | 位置 | 影响 |
|---|------|------|------|
| 4 | 无 dependency_overrides 机制 | 全局缺失 | 无法在测试中替换依赖 |
| 5 | 不支持 `Depends()` 无参形式 | `dependencies.py` | `Annotated[DBSession, Depends()]` 模式不可用 |

### P2 — 健壮性

| # | 问题 | 位置 | 影响 |
|---|------|------|------|
| 6 | ~~Cache key 过于简单~~ | `dependencies.py:198` | 复查后确认：`use_cache=False` 时完全不访问缓存，实际行为正确，**不需要改动** |
| 7 | 无 scope 生命周期控制 | 全局缺失 | 所有 generator 统一在 handler 返回后清理，无法做精细控制（暂不纳入本次改动，留作后续） |
| 8 | `solve_dependant` 中 Environ 注入逻辑不清晰 | `dependencies.py:223-225` | 巧合正确但代码意图不明确 |

---

## 设计方案：基于 AsyncExitStack 的全面重构

### §1 LifespanContext 重写

**文件**: `dependencies.py`

将自定义的 teardown 列表替换为 `contextlib.AsyncExitStack`：

```python
from contextlib import AsyncExitStack

class LifespanContext:
    """Manages teardown functions for async/generator dependencies using AsyncExitStack."""

    def __init__(self) -> None:
        self._stack = AsyncExitStack()

    async def __aenter__(self):
        await self._stack.__aenter__()
        return self

    async def __aexit__(self, *exc_info):
        return await self._stack.__aexit__(*exc_info)

    async def enter_context(self, cm):
        """Enter an async context manager, cleanup registered automatically."""
        return await self._stack.enter_async_context(cm)

    def enter_sync_context(self, cm):
        """Enter a sync context manager."""
        return self._stack.enter_context(cm)
```

**调用方变更** (`async_server.py`):

```python
# 之前
context = LifespanContext()
try:
    return await solve_dependant(dependant, context, cache)
finally:
    await context.run_teardowns()

# 之后
async with LifespanContext() as context:
    return await solve_dependant(dependant, context, cache)
```

**关键保证**:
- 所有 teardown 都会执行（即使前面的 teardown 抛异常）
- Handler 中的异常传播到 generator 的 `yield` 处
- LIFO 顺序清理

### §2 run_with_lifespan_handling 重写

**文件**: `dependencies.py`

```python
from contextlib import asynccontextmanager
import asyncio

async def run_with_lifespan_handling(
    func: Callable,
    kwargs: Dict[str, Any],
    context: LifespanContext,
) -> Any:
    result = func(**kwargs)

    if inspect.isasyncgen(result):
        @asynccontextmanager
        async def _wrap():
            try:
                value = await result.__anext__()
                yield value
            finally:
                try:
                    await result.__anext__()
                except StopAsyncIteration:
                    pass

        return await context.enter_context(_wrap())

    elif inspect.isgenerator(result):
        @asynccontextmanager
        async def _wrap():
            try:
                value = await asyncio.to_thread(next, result)
                yield value
            finally:
                try:
                    await asyncio.to_thread(next, result)
                except StopIteration:
                    pass

        return await context.enter_context(_wrap())

    elif inspect.iscoroutine(result):
        return await result

    return result
```

**决策**: 只有同步 generator 的 `next()` 调用使用 `asyncio.to_thread()`。普通同步依赖函数直接调用（不包装 to_thread）。

### §3 dependency_overrides

**文件**: `async_server.py`, `dependencies.py`

在 `AsyncServer.__init__` 中新增：

```python
self.dependency_overrides: Dict[Callable, Callable] = {}
```

在 `solve_dependency` 中新增 `overrides` 参数：

```python
async def solve_dependency(func, context, cache, use_cache=True, overrides=None):
    actual_func = overrides.get(func, func) if overrides else func
    if use_cache and actual_func in cache:
        return cache[actual_func]
    kwargs = await extract_kwargs_from_signature(actual_func, context, cache, overrides)
    result = await run_with_lifespan_handling(actual_func, kwargs, context)
    if use_cache:
        cache[actual_func] = result
    return result
```

`overrides` 从 `on()` 的 wrapper → `solve_dependant` → `solve_dependency` → `extract_kwargs_from_signature` 逐层传递。

**使用方式**:

```python
# 测试时
sio.dependency_overrides[get_db] = lambda: mock_db
# 清理
sio.dependency_overrides.clear()
```

### §4 Pydantic 验证错误处理

**新增文件**: `exceptions.py`

```python
class SocketIOValidationError(Exception):
    """Raised when incoming data fails Pydantic validation."""
    def __init__(self, errors: list, model_name: str):
        self.errors = errors
        self.model_name = model_name
        super().__init__(f"Validation error for {model_name}: {errors}")
```

**修改文件**: `dependencies.py`

在 `resolve_unknown_param` 和 `solve_dependant` 中所有 `annotation(**data)` 调用处：

```python
from pydantic import ValidationError
from .exceptions import SocketIOValidationError

try:
    kwargs[name] = param.annotation(**val)
except ValidationError as e:
    raise SocketIOValidationError(
        errors=e.errors(),
        model_name=param.annotation.__name__
    ) from e
```

**行为**: 纯抛异常，由用户在 error handler 中自行处理。

**公共 API**: `SocketIOValidationError` 从 `__init__.py` 导出。

### §5a 支持 `Depends()` 无参形式

**文件**: `dependencies.py`

在 `DependencySignature.__init__` 中，当 `dep.dependency is None` 时从类型注解推断 callable：

```python
if dep := get_param_depend(param):
    if dep.dependency is None:
        annotation = param.annotation
        if get_origin(annotation) is Annotated:
            annotation = get_args(annotation)[0]
        if callable(annotation):
            dep = Depends(annotation, use_cache=dep.use_cache)
        else:
            self.params[name] = ("unknown", param)
            continue
    self.params[name] = ("depend", dep)
```

**效果**: 支持 `Annotated[DBSession, Depends()]` 语法。

### §5b Environ 注入统一

**文件**: `dependencies.py`

在 `solve_dependant` 中明确区分 `Environ` 和其他 special params：

```python
for name, annotation in dependant.special_params.items():
    if annotation is Environ:
        kwargs[name] = cache.get("__environ__")
    else:
        key = f"__{annotation.__name__.lower()}__"
        kwargs[name] = cache.get(key)
```

---

## 涉及文件变更清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `fastapi_sio_di/dependencies.py` | 大幅重写 | §1 §2 §4 §5a §5b |
| `fastapi_sio_di/async_server.py` | 小改 | §1（async with）、§3（dependency_overrides） |
| `fastapi_sio_di/exceptions.py` | 新增 | §4 SocketIOValidationError |
| `fastapi_sio_di/__init__.py` | 小改 | 导出 SocketIOValidationError |
| `fastapi_sio_di/utils.py` | 不变 | — |
| `fastapi_sio_di/params.py` | 不变 | — |
| `fastapi_sio_di/async_admin.py` | 不变 | — |

## 公共 API 变化

- **新增**: `AsyncServer.dependency_overrides: Dict[Callable, Callable]`
- **新增**: `SocketIOValidationError` 异常类（从包顶层导出）
- **向后兼容**: 所有现有 API 保持不变

## 不包含在本次改动中

- Scope 生命周期控制（`scope="function"` vs `scope="request"`）—— 留作后续
- BackgroundTasks 支持 —— Socket.IO 场景需求不明确
- 普通同步函数的 `to_thread` 包装 —— 用户选择不包含

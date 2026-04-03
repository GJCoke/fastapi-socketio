"""Baseline regression tests for existing DI behavior.

These must ALL PASS before any refactoring begins.
"""

import pytest
from typing import Annotated
from pydantic import BaseModel
from fastapi.params import Depends

from fastapi_sio_di.params import SID, Environ
from fastapi_sio_di.dependencies import (
    Dependant,
    LifespanContext,
    solve_dependant,
)


class Message(BaseModel):
    msg: str


# ---------- helpers ----------


async def run_handler(handler, make_cache, **cache_kwargs):
    """Simulate running a handler through the DI engine."""
    dependant = Dependant(handler)
    cache = make_cache(**cache_kwargs)
    async with LifespanContext() as context:
        return await solve_dependant(dependant, context, cache)


# ---------- tests ----------


class TestSIDInjection:
    @pytest.mark.asyncio
    async def test_simple_handler_receives_sid(self, make_cache):
        async def handler(sid: SID):
            return sid

        result = await run_handler(handler, make_cache, sid="abc-123")
        assert result == "abc-123"


class TestDataInjection:
    @pytest.mark.asyncio
    async def test_simple_handler_receives_data(self, make_cache):
        async def handler(data):
            return data

        result = await run_handler(handler, make_cache, data="hello")
        assert result == "hello"

    @pytest.mark.asyncio
    async def test_pydantic_model_auto_construction(self, make_cache):
        async def handler(data: Message):
            return data

        result = await run_handler(
            handler,
            make_cache,
            data={"msg": "hi"},
            args=({"msg": "hi"},),
        )
        assert isinstance(result, Message)
        assert result.msg == "hi"


class TestDependsBasic:
    @pytest.mark.asyncio
    async def test_depends_basic(self, make_cache):
        async def get_value():
            return 42

        async def handler(val=Depends(get_value)):
            return val

        result = await run_handler(handler, make_cache)
        assert result == 42

    @pytest.mark.asyncio
    async def test_depends_annotated_style(self, make_cache):
        async def get_value():
            return "annotated"

        async def handler(val: Annotated[str, Depends(get_value)]):
            return val

        result = await run_handler(handler, make_cache)
        assert result == "annotated"

    @pytest.mark.asyncio
    async def test_depends_chain(self, make_cache):
        async def dep_a():
            return "a"

        async def dep_b(a=Depends(dep_a)):
            return a + "b"

        async def dep_c(b=Depends(dep_b)):
            return b + "c"

        async def handler(c=Depends(dep_c)):
            return c

        result = await run_handler(handler, make_cache)
        assert result == "abc"


class TestDependsCache:
    @pytest.mark.asyncio
    async def test_depends_cache_reuse(self, make_cache):
        call_count = 0

        async def counted_dep():
            nonlocal call_count
            call_count += 1
            return call_count

        async def handler(
            a=Depends(counted_dep),
            b=Depends(counted_dep),
        ):
            return a, b

        result = await run_handler(handler, make_cache)
        assert result == (1, 1)
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_depends_use_cache_false(self, make_cache):
        call_count = 0

        async def counted_dep():
            nonlocal call_count
            call_count += 1
            return call_count

        async def handler(
            a=Depends(counted_dep, use_cache=False),
            b=Depends(counted_dep, use_cache=False),
        ):
            return a, b

        result = await run_handler(handler, make_cache)
        assert result == (1, 2)
        assert call_count == 2


class TestGeneratorDependency:
    @pytest.mark.asyncio
    async def test_async_generator_dependency(self, make_cache):
        async def gen_dep():
            yield "gen_value"

        async def handler(val=Depends(gen_dep)):
            return val

        result = await run_handler(handler, make_cache)
        assert result == "gen_value"

    @pytest.mark.asyncio
    async def test_sync_generator_dependency(self, make_cache):
        def gen_dep():
            yield "sync_gen"

        async def handler(val=Depends(gen_dep)):
            return val

        result = await run_handler(handler, make_cache)
        assert result == "sync_gen"


class TestEnvironInjection:
    @pytest.mark.asyncio
    async def test_environ_injection(self, make_cache):
        async def handler(env: Environ):
            return env

        result = await run_handler(
            handler,
            make_cache,
            environ={"path": "/test"},
        )
        assert isinstance(result, Environ)
        assert result.path == "/test"


class TestDefaultParams:
    @pytest.mark.asyncio
    async def test_default_param_preserved(self, make_cache):
        async def handler(sid: SID, mode: str = "default"):
            return sid, mode

        result = await run_handler(handler, make_cache, sid="s1")
        assert result == ("s1", "default")


class TestEmitSerialization:
    @pytest.mark.asyncio
    async def test_emit_pydantic_serialization(self, sio):
        msg = Message(msg="hello")
        result = sio._pydantic_model_to_dict(msg)
        assert result == {"msg": "hello"}
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_emit_non_pydantic_passthrough(self, sio):
        result = sio._pydantic_model_to_dict({"raw": True})
        assert result == {"raw": True}

"""Tests for §5a: Depends() with no argument infers callable from type annotation."""

import pytest
from typing import Annotated
from fastapi.params import Depends

from fastapi_sio_di.dependencies import (
    Dependant,
    LifespanContext,
    solve_dependant,
)


class DBSession:
    """Example injectable class."""

    def __init__(self):
        self.connected = True


async def run_handler(handler, make_cache, **cache_kwargs):
    dependant = Dependant(handler)
    cache = make_cache(**cache_kwargs)
    async with LifespanContext() as context:
        return await solve_dependant(dependant, context, cache)


class TestDependsInference:
    @pytest.mark.asyncio
    async def test_depends_no_arg_infers_from_annotation(self, make_cache):
        """Annotated[DBSession, Depends()] should use DBSession as the dependency."""

        async def handler(db: Annotated[DBSession, Depends()]):
            return db

        result = await run_handler(handler, make_cache)
        assert isinstance(result, DBSession)
        assert result.connected is True

    @pytest.mark.asyncio
    async def test_depends_no_arg_with_non_callable_annotation(self, make_cache):
        """Non-callable annotation + Depends() should treat param as unknown (data)."""

        async def handler(val: Annotated[str, Depends()]):
            return val

        result = await run_handler(handler, make_cache, data="hello", args=("hello",))
        assert result == "hello"

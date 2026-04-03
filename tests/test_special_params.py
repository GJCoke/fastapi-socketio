"""Tests for §5b: SID / Environ injection consistency."""

import pytest
from fastapi.params import Depends

from fastapi_sio_di.params import SID, Environ
from fastapi_sio_di.dependencies import (
    Dependant,
    LifespanContext,
    solve_dependant,
)


async def run_handler(handler, make_cache, **cache_kwargs):
    dependant = Dependant(handler)
    cache = make_cache(**cache_kwargs)
    async with LifespanContext() as context:
        return await solve_dependant(dependant, context, cache)


class TestEnvironConsistency:
    @pytest.mark.asyncio
    async def test_environ_is_environ_instance_in_handler(self, make_cache):
        async def handler(env: Environ):
            return env

        result = await run_handler(
            handler,
            make_cache,
            environ={"path": "/ws", "headers": []},
        )
        assert isinstance(result, Environ)

    @pytest.mark.asyncio
    async def test_environ_is_environ_instance_in_sub_dependency(self, make_cache):
        async def get_env(env: Environ):
            return env

        async def handler(env=Depends(get_env)):
            return env

        result = await run_handler(
            handler,
            make_cache,
            environ={"path": "/ws", "headers": []},
        )
        assert isinstance(result, Environ)
        assert result.path == "/ws"


class TestSIDInSubDependency:
    @pytest.mark.asyncio
    async def test_sid_injection_in_sub_dependency(self, make_cache):
        async def get_sid(sid: SID):
            return sid

        async def handler(s=Depends(get_sid)):
            return s

        result = await run_handler(handler, make_cache, sid="sub-dep-sid")
        assert result == "sub-dep-sid"

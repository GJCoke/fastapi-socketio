"""Tests for §3: dependency_overrides mechanism."""

import pytest
from fastapi.params import Depends

from fastapi_sio_di.params import SID
from fastapi_sio_di.dependencies import (
    Dependant,
    LifespanContext,
    solve_dependant,
)


class TestDependencyOverrides:
    @pytest.mark.asyncio
    async def test_override_replaces_dependency(self, sio, make_cache):
        async def real_dep():
            return "real"

        async def mock_dep():
            return "mocked"

        async def handler(val=Depends(real_dep)):
            return val

        sio.dependency_overrides[real_dep] = mock_dep

        dependant = Dependant(handler)
        cache = make_cache()
        async with LifespanContext() as context:
            result = await solve_dependant(
                dependant,
                context,
                cache,
                overrides=sio.dependency_overrides,
            )
        assert result == "mocked"

    @pytest.mark.asyncio
    async def test_override_affects_sub_dependencies(self, sio, make_cache):
        async def dep_a():
            return "real_a"

        async def dep_b(a=Depends(dep_a)):
            return a + "_b"

        async def mock_a():
            return "mock_a"

        async def handler(b=Depends(dep_b)):
            return b

        sio.dependency_overrides[dep_a] = mock_a

        dependant = Dependant(handler)
        cache = make_cache()
        async with LifespanContext() as context:
            result = await solve_dependant(
                dependant,
                context,
                cache,
                overrides=sio.dependency_overrides,
            )
        assert result == "mock_a_b"

    @pytest.mark.asyncio
    async def test_override_cleanup_restores_original(self, sio, make_cache):
        async def real_dep():
            return "real"

        async def mock_dep():
            return "mocked"

        async def handler(val=Depends(real_dep)):
            return val

        sio.dependency_overrides[real_dep] = mock_dep

        dependant = Dependant(handler)

        # With override
        cache = make_cache()
        async with LifespanContext() as context:
            result = await solve_dependant(
                dependant,
                context,
                cache,
                overrides=sio.dependency_overrides,
            )
        assert result == "mocked"

        # After clearing
        sio.dependency_overrides.clear()
        cache = make_cache()
        async with LifespanContext() as context:
            result = await solve_dependant(
                dependant,
                context,
                cache,
                overrides=sio.dependency_overrides,
            )
        assert result == "real"

    @pytest.mark.asyncio
    async def test_override_with_generator(self, sio, make_cache):
        async def real_dep():
            return "real"

        async def mock_gen():
            yield "gen_mocked"

        async def handler(val=Depends(real_dep)):
            return val

        sio.dependency_overrides[real_dep] = mock_gen

        dependant = Dependant(handler)
        cache = make_cache()
        async with LifespanContext() as context:
            result = await solve_dependant(
                dependant,
                context,
                cache,
                overrides=sio.dependency_overrides,
            )
        assert result == "gen_mocked"

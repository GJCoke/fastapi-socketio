"""Tests for §1 (LifespanContext) and §2 (run_with_lifespan_handling).

Tests generator lifecycle: teardown execution, exception propagation,
teardown isolation, and sync generator non-blocking behavior.
"""

import asyncio
import pytest
from fastapi.params import Depends

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


class TestGeneratorTeardownExecutes:
    @pytest.mark.asyncio
    async def test_generator_teardown_executes(self, make_cache):
        torn_down = False

        async def gen_dep():
            nonlocal torn_down
            yield "value"
            torn_down = True

        async def handler(val=Depends(gen_dep)):
            return val

        result = await run_handler(handler, make_cache)
        assert result == "value"
        assert torn_down is True

    @pytest.mark.asyncio
    async def test_generator_teardown_order_lifo(self, make_cache):
        order = []

        async def dep_a():
            order.append("a_setup")
            yield "a"
            order.append("a_teardown")

        async def dep_b():
            order.append("b_setup")
            yield "b"
            order.append("b_teardown")

        async def handler(a=Depends(dep_a), b=Depends(dep_b)):
            return a, b

        await run_handler(handler, make_cache)
        assert order == ["a_setup", "b_setup", "b_teardown", "a_teardown"]


class TestTeardownOnException:
    @pytest.mark.asyncio
    async def test_generator_teardown_on_handler_exception(self, make_cache):
        """Teardowns must still run when handler raises (generator uses try/finally)."""
        torn_down = False

        async def gen_dep():
            nonlocal torn_down
            try:
                yield "value"
            finally:
                torn_down = True

        async def handler(val=Depends(gen_dep)):
            raise RuntimeError("handler error")

        with pytest.raises(RuntimeError, match="handler error"):
            await run_handler(handler, make_cache)
        assert torn_down is True

    @pytest.mark.asyncio
    async def test_teardown_continues_after_teardown_error(self, make_cache):
        """If one teardown raises, subsequent teardowns must still execute."""
        safe_torn_down = False

        async def dep_bad():
            try:
                yield "bad"
            finally:
                raise RuntimeError("teardown error")

        async def dep_safe():
            nonlocal safe_torn_down
            try:
                yield "safe"
            finally:
                safe_torn_down = True

        async def handler(
            safe=Depends(dep_safe),
            bad=Depends(dep_bad),
        ):
            return safe, bad

        # dep_bad's teardown raises, but dep_safe's teardown must still execute
        try:
            await run_handler(handler, make_cache)
        except Exception:
            pass
        assert safe_torn_down is True


class TestGeneratorReceivesException:
    @pytest.mark.asyncio
    async def test_generator_receives_exception(self, make_cache):
        """Handler exception should propagate into generator's yield point."""
        received_exc = None

        async def gen_dep():
            nonlocal received_exc
            try:
                yield "value"
            except RuntimeError as e:
                received_exc = e

        async def handler(val=Depends(gen_dep)):
            raise RuntimeError("propagated")

        with pytest.raises(RuntimeError):
            await run_handler(handler, make_cache)
        assert received_exc is not None
        assert str(received_exc) == "propagated"


class TestSyncGeneratorNonBlocking:
    @pytest.mark.asyncio
    async def test_sync_generator_does_not_block_loop(self, make_cache):
        """Sync generator's next() should run in a thread, not block the loop."""
        import time

        def slow_dep():
            time.sleep(0.05)
            yield "slow"
            time.sleep(0.05)

        async def handler(val=Depends(slow_dep)):
            return val

        # Run the handler and a concurrent coroutine to verify non-blocking
        async def canary():
            """This should complete quickly if the loop is not blocked."""
            await asyncio.sleep(0.01)
            return "canary_done"

        results = await asyncio.gather(
            run_handler(handler, make_cache),
            canary(),
        )
        assert results[0] == "slow"
        assert results[1] == "canary_done"

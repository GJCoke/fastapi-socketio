"""Integration tests for cross-instance call (requires Redis)."""
import asyncio
import pytest
import pytest_asyncio
import redis.asyncio as aioredis
from fastapi_sio_di import AsyncServer
from fastapi_sio_di.manager import AsyncRedisCallManager

REDIS_URL = "redis://localhost:6379/0"

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(autouse=True)
async def skip_without_redis():
    """Skip integration tests if Redis is not available."""
    try:
        r = aioredis.from_url(REDIS_URL)
        await r.ping()
        await r.aclose()
    except Exception:
        pytest.skip("Redis not available")


def _create_server(manager):
    """Create an AsyncServer with the given manager."""
    server = AsyncServer(client_manager=manager)
    return server


@pytest_asyncio.fixture
async def two_servers():
    """Create two server instances sharing the same Redis."""
    mgr_a = AsyncRedisCallManager(REDIS_URL, channel="test-call")
    mgr_b = AsyncRedisCallManager(REDIS_URL, channel="test-call")
    server_a = _create_server(mgr_a)
    server_b = _create_server(mgr_b)
    yield server_a, server_b
    # Cleanup
    if mgr_a.redis:
        await mgr_a.redis.aclose()
    if mgr_b.redis:
        await mgr_b.redis.aclose()


class TestCrossInstanceCallIntegration:
    @pytest.mark.asyncio
    async def test_basic_cross_instance_call(self, two_servers):
        """
        Server A calls a client connected to Server B.
        Simulates the Redis-level flow: B writes result, A reads via BLPOP.
        """
        server_a, server_b = two_servers
        mgr_a = server_a.manager
        mgr_b = server_b.manager

        if not mgr_a.connected:
            mgr_a._redis_connect()
        if not mgr_b.connected:
            mgr_b._redis_connect()

        call_id = mgr_a._generate_call_id()
        key = f"sio:call:{call_id}"

        # Simulate: server_b receives the call and writes result to Redis
        result_data = ("hello from client",)
        payload = mgr_b._pack_result("ok", data=result_data)
        await mgr_b.redis.rpush(key, payload)
        await mgr_b.redis.expire(key, 10)

        # Server A does BLPOP
        result = await mgr_a.redis.blpop(key, timeout=5)
        assert result is not None
        unpacked = mgr_a._unpack_result(result[1])
        assert unpacked == ("hello from client",)

    @pytest.mark.asyncio
    async def test_blpop_timeout(self, two_servers):
        """BLPOP times out when no response is written."""
        server_a, _ = two_servers
        mgr_a = server_a.manager

        if not mgr_a.connected:
            mgr_a._redis_connect()

        call_id = mgr_a._generate_call_id()
        key = f"sio:call:{call_id}"

        result = await mgr_a.redis.blpop(key, timeout=1)
        assert result is None

    @pytest.mark.asyncio
    async def test_concurrent_calls_no_interference(self, two_servers):
        """Multiple concurrent calls don't interfere with each other."""
        server_a, server_b = two_servers
        mgr_a = server_a.manager
        mgr_b = server_b.manager

        if not mgr_a.connected:
            mgr_a._redis_connect()
        if not mgr_b.connected:
            mgr_b._redis_connect()

        call_id_1 = mgr_a._generate_call_id()
        call_id_2 = mgr_a._generate_call_id()
        key_1 = f"sio:call:{call_id_1}"
        key_2 = f"sio:call:{call_id_2}"

        # Write results in reverse order
        await mgr_b.redis.rpush(key_2, mgr_b._pack_result("ok", data=("result-2",)))
        await mgr_b.redis.rpush(key_1, mgr_b._pack_result("ok", data=("result-1",)))
        await mgr_b.redis.expire(key_1, 10)
        await mgr_b.redis.expire(key_2, 10)

        r1 = await mgr_a.redis.blpop(key_1, timeout=5)
        r2 = await mgr_a.redis.blpop(key_2, timeout=5)

        assert mgr_a._unpack_result(r1[1]) == ("result-1",)
        assert mgr_a._unpack_result(r2[1]) == ("result-2",)

    @pytest.mark.asyncio
    async def test_key_expires_after_ttl(self, two_servers):
        """Redis key auto-expires after timeout + 5s."""
        server_a, server_b = two_servers
        mgr_a = server_a.manager
        mgr_b = server_b.manager

        if not mgr_a.connected:
            mgr_a._redis_connect()
        if not mgr_b.connected:
            mgr_b._redis_connect()

        call_id = mgr_a._generate_call_id()
        key = f"sio:call:{call_id}"

        await mgr_b.redis.rpush(key, mgr_b._pack_result("ok", data=("x",)))
        await mgr_b.redis.expire(key, 2)

        ttl = await mgr_a.redis.ttl(key)
        assert ttl > 0

        await asyncio.sleep(2.5)
        exists = await mgr_a.redis.exists(key)
        assert exists == 0


class TestHighConcurrency:
    @pytest.mark.asyncio
    async def test_100_concurrent_calls(self, two_servers):
        """100 concurrent calls each get their correct response."""
        server_a, server_b = two_servers
        mgr_a = server_a.manager
        mgr_b = server_b.manager

        if not mgr_a.connected:
            mgr_a._redis_connect()
        if not mgr_b.connected:
            mgr_b._redis_connect()

        n = 100
        call_ids = [mgr_a._generate_call_id() for _ in range(n)]
        keys = [f"sio:call:{cid}" for cid in call_ids]

        for i, key in enumerate(keys):
            await mgr_b.redis.rpush(key, mgr_b._pack_result("ok", data=(f"resp-{i}",)))
            await mgr_b.redis.expire(key, 30)

        async def blpop_one(k, idx):
            r = await mgr_a.redis.blpop(k, timeout=5)
            return idx, mgr_a._unpack_result(r[1])

        results = await asyncio.gather(*[blpop_one(k, i) for i, k in enumerate(keys)])

        for idx, val in results:
            assert val == (f"resp-{idx}",)

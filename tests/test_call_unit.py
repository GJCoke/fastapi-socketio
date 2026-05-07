"""Unit tests for cross-instance call functionality."""
import pytest
import msgpack
from fastapi_sio_di.exceptions import CallError
from fastapi_sio_di.manager import AsyncRedisCallManager


class TestCallError:
    def test_call_error_attributes(self):
        err = CallError("not_found", "sid not connected")
        assert err.code == "not_found"
        assert err.message == "sid not connected"
        assert "not_found" in str(err)

    def test_call_error_is_exception(self):
        err = CallError("timeout", "call timed out")
        assert isinstance(err, Exception)


class TestCallIdGeneration:
    def test_unique_ids(self):
        """Consecutive call_ids are unique."""
        mgr = AsyncRedisCallManager.__new__(AsyncRedisCallManager)
        mgr.host_id = "host-abc"
        mgr._call_counter = 0
        id1 = mgr._generate_call_id()
        id2 = mgr._generate_call_id()
        assert id1 != id2

    def test_format(self):
        """call_id format is {host_id}:{counter}."""
        mgr = AsyncRedisCallManager.__new__(AsyncRedisCallManager)
        mgr.host_id = "host-xyz"
        mgr._call_counter = 0
        call_id = mgr._generate_call_id()
        assert call_id == "host-xyz:1"

    def test_cross_manager_uniqueness(self):
        """Different managers produce different call_ids."""
        mgr1 = AsyncRedisCallManager.__new__(AsyncRedisCallManager)
        mgr1.host_id = "host-1"
        mgr1._call_counter = 0

        mgr2 = AsyncRedisCallManager.__new__(AsyncRedisCallManager)
        mgr2.host_id = "host-2"
        mgr2._call_counter = 0

        assert mgr1._generate_call_id() != mgr2._generate_call_id()


class TestResultSerialization:
    def test_pack_success(self):
        mgr = AsyncRedisCallManager.__new__(AsyncRedisCallManager)
        payload = mgr._pack_result("ok", data=("hello",))
        result = msgpack.unpackb(payload, raw=False)
        assert result == {"status": "ok", "data": ["hello"]}

    def test_pack_error(self):
        mgr = AsyncRedisCallManager.__new__(AsyncRedisCallManager)
        payload = mgr._pack_result("error", code="not_found", message="sid not connected")
        result = msgpack.unpackb(payload, raw=False)
        assert result == {"status": "error", "code": "not_found", "message": "sid not connected"}

    def test_unpack_success(self):
        mgr = AsyncRedisCallManager.__new__(AsyncRedisCallManager)
        payload = msgpack.packb({"status": "ok", "data": ["world"]})
        result = mgr._unpack_result(payload)
        assert result == ("world",)

    def test_unpack_success_multiple_args(self):
        mgr = AsyncRedisCallManager.__new__(AsyncRedisCallManager)
        payload = msgpack.packb({"status": "ok", "data": ["a", "b", "c"]})
        result = mgr._unpack_result(payload)
        assert result == ("a", "b", "c")

    def test_unpack_success_empty(self):
        mgr = AsyncRedisCallManager.__new__(AsyncRedisCallManager)
        payload = msgpack.packb({"status": "ok", "data": []})
        result = mgr._unpack_result(payload)
        assert result is None

    def test_unpack_error_raises(self):
        mgr = AsyncRedisCallManager.__new__(AsyncRedisCallManager)
        payload = msgpack.packb({"status": "error", "code": "no_ack", "message": "client did not acknowledge"})
        with pytest.raises(CallError) as exc_info:
            mgr._unpack_result(payload)
        assert exc_info.value.code == "no_ack"


from unittest.mock import AsyncMock, MagicMock, patch


class TestEmitWithCallId:
    @pytest.mark.asyncio
    async def test_publishes_correct_message(self):
        """_emit_with_call_id publishes message with all required fields."""
        mgr = AsyncRedisCallManager.__new__(AsyncRedisCallManager)
        mgr.host_id = "host-a"
        mgr.json = MagicMock()
        mgr.json.dumps = MagicMock(side_effect=lambda x: x)
        mgr.redis = AsyncMock()
        mgr.channel = "socketio"
        mgr.connected = True

        await mgr._emit_with_call_id(
            event="get_status",
            data={"key": "val"},
            namespace="/",
            room="sid-123",
            call_id="host-a:1",
            timeout=30,
        )

        mgr.redis.publish.assert_called_once()
        published = mgr.redis.publish.call_args[0][1]
        assert published["method"] == "call_emit"
        assert published["event"] == "get_status"
        assert published["data"] == [{"key": "val"}]
        assert published["namespace"] == "/"
        assert published["room"] == "sid-123"
        assert published["call_id"] == "host-a:1"
        assert published["timeout"] == 30
        assert published["host_id"] == "host-a"


class TestHandleCallEmit:
    @pytest.mark.asyncio
    async def test_ignores_non_local_sid(self):
        """Ignores call_emit when target sid is not local."""
        mgr = AsyncRedisCallManager.__new__(AsyncRedisCallManager)
        mgr.host_id = "host-b"
        mgr.is_connected = MagicMock(return_value=False)
        mgr._local_emit = AsyncMock()

        message = {
            "method": "call_emit",
            "event": "ping",
            "data": [None],
            "namespace": "/",
            "room": "sid-999",
            "call_id": "host-a:1",
            "timeout": 10,
            "host_id": "host-a",
        }

        await mgr._handle_call_emit(message)
        mgr._local_emit.assert_not_called()

    @pytest.mark.asyncio
    async def test_emits_locally_and_registers_callback(self):
        """When target sid is local, emits event and registers redis callback."""
        mgr = AsyncRedisCallManager.__new__(AsyncRedisCallManager)
        mgr.host_id = "host-b"
        mgr.is_connected = MagicMock(return_value=True)
        mgr._call_counter = 0
        mgr._local_emit = AsyncMock()
        mgr.redis = AsyncMock()

        message = {
            "method": "call_emit",
            "event": "get_status",
            "data": ["request_data"],
            "namespace": "/",
            "room": "sid-123",
            "call_id": "host-a:1",
            "timeout": 30,
            "host_id": "host-a",
        }

        await mgr._handle_call_emit(message)

        mgr._local_emit.assert_called_once()
        call_args = mgr._local_emit.call_args
        assert call_args[0][0] == "get_status"  # event
        assert call_args[0][1] == "request_data"  # data (unwrapped from single-element list)
        assert call_args[1]["room"] == "sid-123"
        assert call_args[1]["namespace"] == "/"
        assert call_args[1]["callback"] is not None  # callback registered


from fastapi_sio_di import AsyncServer


class TestServerCallLocalShortCircuit:
    @pytest.mark.asyncio
    async def test_local_sid_uses_super_call(self):
        """When target is connected locally, uses parent call()."""
        server = AsyncServer()
        server.manager = MagicMock(spec=AsyncRedisCallManager)
        server.manager.is_connected = MagicMock(return_value=True)

        with patch("socketio.AsyncServer.call", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = "local_result"
            result = await server.call("event", data="x", to="local-sid", timeout=5)

        assert result == "local_result"
        mock_call.assert_called_once()

    @pytest.mark.asyncio
    async def test_non_call_manager_uses_super_call(self):
        """When manager is not AsyncRedisCallManager, uses parent call()."""
        server = AsyncServer()
        # Default manager is not AsyncRedisCallManager

        with patch("socketio.AsyncServer.call", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = "fallback"
            result = await server.call("event", data="x", to="sid-1", timeout=5)

        assert result == "fallback"


class TestServerCallCrossInstance:
    @pytest.mark.asyncio
    async def test_cross_instance_call_flow(self):
        """Full cross-instance call: emit_with_call_id + BLPOP."""
        server = AsyncServer()
        mgr = MagicMock(spec=AsyncRedisCallManager)
        mgr.is_connected = MagicMock(return_value=False)
        mgr.host_id = "host-a"
        mgr._call_counter = 0
        mgr._generate_call_id = AsyncRedisCallManager._generate_call_id.__get__(mgr)
        mgr._unpack_result = AsyncRedisCallManager._unpack_result.__get__(mgr)
        mgr._emit_with_call_id = AsyncMock()

        packed = msgpack.packb({"status": "ok", "data": ["response_data"]})
        mgr.redis = AsyncMock()
        mgr.redis.blpop = AsyncMock(return_value=(b"sio:call:host-a:1", packed))

        server.manager = mgr

        result = await server.call("get_info", data="req", to="remote-sid", timeout=10)

        assert result == ("response_data",)
        mgr._emit_with_call_id.assert_called_once()
        mgr.redis.blpop.assert_called_once_with("sio:call:host-a:1", timeout=10)

    @pytest.mark.asyncio
    async def test_cross_instance_call_timeout(self):
        """BLPOP returns None -> TimeoutError."""
        server = AsyncServer()
        mgr = MagicMock(spec=AsyncRedisCallManager)
        mgr.is_connected = MagicMock(return_value=False)
        mgr.host_id = "host-a"
        mgr._call_counter = 0
        mgr._generate_call_id = AsyncRedisCallManager._generate_call_id.__get__(mgr)
        mgr._emit_with_call_id = AsyncMock()
        mgr.redis = AsyncMock()
        mgr.redis.blpop = AsyncMock(return_value=None)

        server.manager = mgr

        with pytest.raises(TimeoutError):
            await server.call("ping", to="gone-sid", timeout=2)

    @pytest.mark.asyncio
    async def test_cross_instance_call_error_response(self):
        """Error response from remote -> CallError."""
        server = AsyncServer()
        mgr = MagicMock(spec=AsyncRedisCallManager)
        mgr.is_connected = MagicMock(return_value=False)
        mgr.host_id = "host-a"
        mgr._call_counter = 0
        mgr._generate_call_id = AsyncRedisCallManager._generate_call_id.__get__(mgr)
        mgr._unpack_result = AsyncRedisCallManager._unpack_result.__get__(mgr)
        mgr._emit_with_call_id = AsyncMock()

        packed = msgpack.packb({"status": "error", "code": "no_ack", "message": "client did not acknowledge"})
        mgr.redis = AsyncMock()
        mgr.redis.blpop = AsyncMock(return_value=(b"key", packed))

        server.manager = mgr

        with pytest.raises(CallError) as exc_info:
            await server.call("ping", to="sid-x", timeout=5)
        assert exc_info.value.code == "no_ack"

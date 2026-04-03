import pytest
from fastapi_sio_di import AsyncServer
from fastapi_sio_di.params import SID, Environ


@pytest.fixture
def sio():
    """Create a clean AsyncServer instance."""
    return AsyncServer()


@pytest.fixture
def make_cache():
    """Create a pre-populated DI cache dict."""

    def _make(sid="test-sid", data=None, environ=None, args=None):
        env = Environ(environ or {})
        if args is None:
            args = (data,) if data is not None else ()
        return {
            "__sid__": sid,
            "__data__": data,
            "__environ__": env,
            "__args__": args,
            "__kwargs__": {},
        }

    return _make

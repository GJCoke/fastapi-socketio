from typing import Any, Dict, Optional

class SID(str):
    """
    Marker class to indicate a 'sid' dependency.

    Used as a type annotation to signal that the parameter
    should be resolved from the socket session ID.

    Examples:
        @sio.on("message")
        async def message(sid: SID):
            print(sid)
    """


class Environ:
    """
    A wrapper for the WSGI/ASGI environment dictionary.
    Provides easy access to common request information.
    """
    def __init__(self, env: Dict[str, Any]):
        self._env = env

    def __getitem__(self, key: str) -> Any:
        return self._env[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self._env.get(key, default)

    @property
    def scope(self) -> Dict[str, Any]:
        """Returns the raw ASGI scope / WSGI environ dictionary."""
        return self._env

    @property
    def headers(self) -> Dict[str, str]:
        """Returns a dictionary of headers (case-insensitive keys not guaranteed)."""
        # For ASGI scope, headers are a list of (byte-key, byte-value)
        if "headers" in self._env:
            return {
                k.decode("latin-1"): v.decode("latin-1")
                for k, v in self._env["headers"]
            }
        # For WSGI, headers are prefixed with HTTP_
        return {
            k[5:].replace("_", "-").lower(): v
            for k, v in self._env.items()
            if k.startswith("HTTP_")
        }

    @property
    def client(self) -> Optional[tuple]:
        """Returns (host, port) tuple of the client."""
        return self._env.get("client") or self._env.get("REMOTE_ADDR")

    @property
    def path(self) -> str:
        """Returns the request path."""
        return self._env.get("path") or self._env.get("PATH_INFO", "")

    @property
    def query_string(self) -> bytes:
        """Returns the raw query string."""
        return self._env.get("query_string") or self._env.get("QUERY_STRING", "").encode()

    @property
    def http_version(self) -> str:
        """Returns the HTTP version."""
        return self._env.get("http_version") or self._env.get("SERVER_PROTOCOL", "")

    def __repr__(self) -> str:
        return f"Environ({self._env.__repr__()})"

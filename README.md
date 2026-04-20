<div align="center">
  <h1>FastAPI-SIO-DI</h1>
  <span>English | <a href="./docs/README-CN.md">中文</a></span>
</div>

[![PyPI](https://img.shields.io/pypi/v/fastapi-sio-di.svg)](https://pypi.org/project/fastapi-sio-di/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](https://github.com/GJCoke/fastapi-socketio/blob/main/LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/downloads/)

FastAPI-SIO-DI is a library tailored for integrating Socket.IO with FastAPI. It allows you to develop real-time WebSocket applications using the familiar **FastAPI style** (Dependency Injection, Pydantic models).

## Key Features

*   **Native Dependency Injection**: Use `Depends` directly in Socket.IO event handlers, just like in HTTP endpoints. Supports `Annotated[T, Depends()]` style.
*   **Pydantic Model Support**: Automatically validate and convert incoming JSON data to Pydantic objects; automatically serialize models when emitting events.
*   **Interactive API Documentation**: Auto-generated Swagger-like docs UI with live Socket.IO testing — call `setup_docs()` and you're done.
*   **Admin UI Instrumentation**: Built-in support for the [Socket.IO Admin UI](https://admin.socket.io/) for real-time server monitoring.
*   **Zero-Intrusion Integration**: Built on `python-socketio`, fully compatible with its ecosystem. Simply replace the `AsyncServer` class.

## Installation

```bash
pip install fastapi-sio-di
```

## Quick Start

```python
from fastapi import FastAPI, Depends
from fastapi_sio_di import AsyncServer, SID, Environ
from pydantic import BaseModel
import socketio

# 1. Initialize FastAPI and Socket.IO
app = FastAPI()
sio = AsyncServer(async_mode="asgi", cors_allowed_origins="*")
sio_app = socketio.ASGIApp(sio)
app.mount("/socket.io", sio_app)


# 2. Define Pydantic Model
class ChatMessage(BaseModel):
    user: str
    text: str

class Reply(BaseModel):
    text: str
    from_user: str


# 3. Define Dependency
async def get_current_user(token: str = "anonymous"):
    return {"username": "user_" + token}


# 4. Write Event Handlers
@sio.on("connect")
async def on_connect(sid: SID, environ: Environ, auth: dict):
    print(f"New connection: {sid}, client: {environ.client}")

@sio.on("chat", response_model=Reply)
async def handle_chat(
    sid: SID,
    data: ChatMessage,
    user=Depends(get_current_user),
):
    print(f"Message from {user['username']}: {data.text}")
    return Reply(text=f"Echo: {data.text}", from_user=user["username"])


# 5. Enable interactive docs and admin UI
sio.setup_docs(app, title="My Socket.IO API", version="1.0.0")
sio.instrument({"username": "admin", "password": "secret"})
```

Run with:

```bash
uvicorn main:app
```

Then open:
- `http://localhost:8000/sio/docs` — Interactive API documentation
- `https://admin.socket.io/` — Admin UI (connect to your server)

## API Reference

### AsyncServer

Drop-in replacement for `socketio.AsyncServer` with added features:

```python
sio = AsyncServer(async_mode="asgi", cors_allowed_origins="*", serializer="model_dump")
```

| Parameter | Description |
|---|---|
| `serializer` | Method name for Pydantic serialization (default: `model_dump`, falls back to `dict`) |
| *other args* | Passed through to `socketio.AsyncServer` |

#### `@sio.on(event, namespace, response_model)`

Register an event handler with dependency injection support.

```python
@sio.on("message", response_model=Reply)
async def handle(sid: SID, data: MyModel, db=Depends(get_db)):
    ...
```

The `response_model` parameter enables return-value serialization and appears in the generated docs schema.

#### `sio.setup_docs(app, path, title, version)`

Mount interactive API documentation.

```python
sio.setup_docs(app, path="/sio/docs", title="My API", version="1.0.0")
```

This creates two endpoints:
- `{path}` — Interactive HTML docs with live testing
- `{path}/schema` — JSON schema endpoint

#### `sio.instrument(auth)`

Enable [Socket.IO Admin UI](https://admin.socket.io/) integration.

```python
sio.instrument({"username": "admin", "password": "secret"})
```

#### `sio.dependency_overrides`

Override dependencies for testing, same pattern as FastAPI:

```python
sio.dependency_overrides[get_db] = lambda: mock_db
```

### Type Markers

#### `SID`

Injects the session ID of the current connection:

```python
@sio.on("event")
async def handler(sid: SID):
    print(f"Session: {sid}")  # sid is a str
```

#### `Environ`

Injects the handshake environment with convenient property access:

```python
@sio.on("connect")
async def on_connect(sid: SID, environ: Environ):
    environ.scope       # ASGI scope dict
    environ.headers     # dict of HTTP headers
    environ.client      # (host, port) tuple
    environ.path        # request path
    environ.query_string  # raw query string
    environ.http_version  # e.g. "1.1"
```

### Dependency Injection

Full support for FastAPI-style `Depends`, including:

**Standard style:**
```python
@sio.on("event")
async def handler(db=Depends(get_db)):
    ...
```

**Annotated style:**
```python
from typing import Annotated

DB = Annotated[Session, Depends(get_db)]

@sio.on("event")
async def handler(db: DB):
    ...
```

**Generator dependencies** (with proper lifecycle management):
```python
async def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        await db.close()
```

**Dependency chains** are fully supported — dependencies can depend on other dependencies, with caching to avoid redundant resolution.

### Connect Handler

The `connect` event handler receives `auth` data sent by the client:

```python
@sio.on("connect")
async def on_connect(sid: SID, environ: Environ, auth: dict):
    if not validate_token(auth.get("token")):
        raise ConnectionRefusedError("Invalid token")
```

### Error Handling

When Pydantic validation fails, a `SocketIOValidationError` is raised with structured error details:

```python
from fastapi_sio_di import SocketIOValidationError

try:
    ...
except SocketIOValidationError as e:
    print(e.errors)      # List of validation errors
    print(e.model_name)  # Name of the Pydantic model
```

## Requirements

- Python 3.10+
- `python-socketio >= 5.16.1`

## Contributing

Issues and Pull Requests are welcome!

## License

[MIT License](./LICENSE)

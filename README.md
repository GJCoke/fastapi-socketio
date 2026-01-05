
# FastAPI-SIO-DI

**FastAPI-SIO-DI** is a library tailored for integrating Socket.IO with FastAPI. It allows you to develop real-time WebSocket applications using the familiar **FastAPI style** (Dependency Injection, Pydantic models).

## Key Features

*   **Native Dependency Injection**: Use `Depends` directly in Socket.IO event handlers, just like in HTTP endpoints.
*   **Pydantic Model Support**: Automatically validate and convert incoming JSON data to Pydantic objects; automatically serialize models when emitting events.
*   **Zero-Intrusion Integration**: Built on `python-socketio`, fully compatible with its ecosystem. Simply replace the `AsyncServer` class.

## Installation

```bash
pip install fastapi-sio-di
```

## Quick Start

### 1. Basic Example

Create a `main.py` file:

```python
from fastapi import FastAPI, Depends
from fastapi_sio_di import AsyncServer, SID, Environ
from pydantic import BaseModel
import socketio

# 1. Initialize FastAPI and Socket.IO
app = FastAPI()
# Use AsyncServer provided by fastapi_sio_di
sio = AsyncServer(async_mode="asgi", cors_allowed_origins="*")
sio_app = socketio.ASGIApp(sio)
app.mount("/socket.io", sio_app)


# 2. Define Pydantic Model
class ChatMessage(BaseModel):
    user: str
    text: str


# 3. Define Dependency
async def get_current_user(token: str):
    # Perform database query or authentication here
    return {"username": "user_" + token}


# 4. Write Event Handlers
@sio.on("connect")
async def on_connect(sid: SID, environ: Environ):
    print(f"New connection: {sid}")
    # You can get headers from environ, e.g., auth token
    # print(environ.get('HTTP_AUTHORIZATION'))


@sio.on("chat")
async def handle_chat(
    sid: SID,
    data: ChatMessage,  # Automatic Pydantic model validation & conversion
    token: str = "default_token",  # Supports standard arguments
    user=Depends(get_current_user)  # Supports FastAPI Dependency Injection!
):
    print(f"Received message: {data.text} from {user['username']}")

    # Emit Pydantic models directly; they are automatically serialized to JSON
    await sio.emit("reply", data, room=sid)
```

### 2. Run

```bash
uvicorn main:app
```

You can now connect to `http://localhost:8000` using any Socket.IO client.

## Advanced Usage

### Dependency Injection

The biggest highlight of `FastAPI-SIO-DI` is support for `Depends`. This means you can reuse existing FastAPI dependency logic (such as database sessions, user authentication).

```python
from sqlalchemy.orm import Session
from app.db import get_db

@sio.on("create_item")
async def create_item(data: ItemCreate, db: Session = Depends(get_db)):
    # The db session is automatically created and closed after the event handler finishes
    new_item = Item(**data.dict())
    db.add(new_item)
    db.commit()
```

### Accessing Context Information

Use type annotations `SID` and `Environ` to access Socket.IO context information.

*   `sid: SID`: The Session ID of the current connection.
*   `environ: Environ`: The environment information during handshake (includes Headers, etc.).

```python
@sio.on("connect")
async def connect(sid: SID, environ: Environ):
    # Get client IP
    client_ip = environ.get('REMOTE_ADDR')
    print(f"Client {sid} connected from {client_ip}")
```

### Serialization Configuration

When initializing `AsyncServer`, you can specify the method name used for serializing Pydantic models (defaults to `model_dump` or `dict`).

```python
# If your model has a custom .json() method
sio = AsyncServer(serializer="json")
```

## Contributing

Issues and Pull Requests are welcome!

## License

MIT License
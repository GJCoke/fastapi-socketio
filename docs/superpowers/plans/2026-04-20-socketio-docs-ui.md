# Socket.IO API Docs UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Swagger-like interactive documentation page to `fastapi-sio-di` that auto-generates from registered Socket.IO event handlers, with live testing via embedded socket.io-client.

**Architecture:** Extend `AsyncServer.on()` to store event metadata (`EventDoc`) in a registry. A new `docs.py` module generates JSON Schema from the registry and serves it via two Starlette routes (`/sio-docs` HTML page, `/sio-docs/schema` JSON endpoint). The HTML template uses vanilla JS + socket.io-client CDN for a Swagger-style accordion UI with Try-it-out panels.

**Tech Stack:** Python 3.10+, Pydantic V2 (`model_json_schema`), Starlette routes, vanilla HTML/JS, socket.io-client 4.x CDN

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `fastapi_sio_di/docs.py` | Create | `EventDoc` dataclass, `build_schema()` JSON generation, `setup_docs()` route registration |
| `fastapi_sio_di/templates/docs.html` | Create | HTML template: accordion layout, light theme, Try-it-out panel, socket.io-client integration |
| `fastapi_sio_di/async_server.py` | Modify | Add `_event_registry`, collect `EventDoc` in `on()`, add `response_model` param, expose `setup_docs()` |
| `fastapi_sio_di/__init__.py` | Modify | Export `EventDoc` |
| `tests/test_docs.py` | Create | Tests for event registry, schema generation, route responses |

---

### Task 1: EventDoc dataclass and schema generation

**Files:**
- Create: `fastapi_sio_di/docs.py`
- Test: `tests/test_docs.py`

- [ ] **Step 1: Write failing tests for EventDoc and schema generation**

```python
# tests/test_docs.py
"""Tests for Socket.IO docs: EventDoc registry and schema generation."""

import inspect
import pytest
from typing import Optional
from pydantic import BaseModel

from fastapi_sio_di.docs import EventDoc, build_event_schema, build_schema
from fastapi_sio_di.dependencies import Dependant
from fastapi_sio_di.params import SID


class ChatMessage(BaseModel):
    content: str
    room: Optional[str] = None


class ChatResponse(BaseModel):
    status: str
    timestamp: float


# --- EventDoc creation ---

class TestEventDoc:
    def test_from_handler_extracts_docstring(self):
        async def handle_chat(sid: SID, data: ChatMessage):
            """Process chat messages.

            Receives chat content from the client and broadcasts it.
            """
            pass

        dependant = Dependant(handle_chat)
        doc = EventDoc.from_handler(
            event="chat",
            namespace="/",
            handler=handle_chat,
            dependant=dependant,
            response_model=ChatResponse,
        )

        assert doc.event == "chat"
        assert doc.namespace == "/"
        assert doc.summary == "Process chat messages."
        assert "broadcasts" in doc.description
        assert doc.response_model is ChatResponse
        assert doc.is_connect is False
        assert doc.is_disconnect is False

    def test_from_handler_no_docstring(self):
        async def handle_ping(sid: SID):
            pass

        dependant = Dependant(handle_ping)
        doc = EventDoc.from_handler(
            event="ping",
            namespace="/",
            handler=handle_ping,
            dependant=dependant,
        )

        assert doc.summary is None
        assert doc.description is None

    def test_from_handler_connect_event(self):
        async def on_connect(sid: SID):
            """Client connected."""
            pass

        dependant = Dependant(on_connect)
        doc = EventDoc.from_handler(
            event="connect",
            namespace="/",
            handler=on_connect,
            dependant=dependant,
        )

        assert doc.is_connect is True
        assert doc.is_disconnect is False

    def test_from_handler_disconnect_event(self):
        async def on_disconnect(sid: SID):
            pass

        dependant = Dependant(on_disconnect)
        doc = EventDoc.from_handler(
            event="disconnect",
            namespace="/",
            handler=on_disconnect,
            dependant=dependant,
        )

        assert doc.is_disconnect is True

    def test_response_model_from_return_annotation(self):
        async def handle_chat(sid: SID, data: ChatMessage) -> ChatResponse:
            pass

        dependant = Dependant(handle_chat)
        doc = EventDoc.from_handler(
            event="chat",
            namespace="/",
            handler=handle_chat,
            dependant=dependant,
            response_model=None,  # not provided via decorator
        )

        assert doc.response_model is ChatResponse

    def test_decorator_response_model_overrides_annotation(self):
        class AltResponse(BaseModel):
            ok: bool

        async def handle_chat(sid: SID) -> ChatResponse:
            pass

        dependant = Dependant(handle_chat)
        doc = EventDoc.from_handler(
            event="chat",
            namespace="/",
            handler=handle_chat,
            dependant=dependant,
            response_model=AltResponse,
        )

        assert doc.response_model is AltResponse


# --- Single event schema ---

class TestBuildEventSchema:
    def test_pydantic_request_schema(self):
        async def handler(sid: SID, data: ChatMessage):
            """Chat handler."""
            pass

        dependant = Dependant(handler)
        doc = EventDoc.from_handler(
            event="chat",
            namespace="/",
            handler=handler,
            dependant=dependant,
            response_model=ChatResponse,
        )

        schema = build_event_schema(doc)

        assert schema["event"] == "chat"
        assert schema["summary"] == "Chat handler."
        assert schema["direction"] == "client_to_server"
        assert schema["is_connect"] is False

        # request schema
        req = schema["request_schema"]
        assert req["title"] == "ChatMessage"
        assert "content" in req["properties"]
        assert "content" in req["required"]

        # response schema
        resp = schema["response_schema"]
        assert resp["title"] == "ChatResponse"
        assert "status" in resp["properties"]

        # params
        param_names = [p["name"] for p in schema["params"]]
        assert "sid" in param_names
        assert "data" in param_names

    def test_primitive_request_schema(self):
        async def handler(sid: SID, msg: str):
            pass

        dependant = Dependant(handler)
        doc = EventDoc.from_handler(
            event="echo",
            namespace="/",
            handler=handler,
            dependant=dependant,
        )

        schema = build_event_schema(doc)
        assert schema["request_schema"] == {"type": "string"}
        assert schema["response_schema"] is None

    def test_no_data_param(self):
        async def handler(sid: SID):
            pass

        dependant = Dependant(handler)
        doc = EventDoc.from_handler(
            event="ping",
            namespace="/",
            handler=handler,
            dependant=dependant,
        )

        schema = build_event_schema(doc)
        assert schema["request_schema"] is None


# --- Full schema ---

class TestBuildSchema:
    def test_groups_by_namespace(self):
        async def h1(sid: SID, data: ChatMessage):
            """Default ns handler."""
            pass

        async def h2(sid: SID):
            """Chat ns handler."""
            pass

        registry = [
            EventDoc.from_handler("chat", "/", h1, Dependant(h1), response_model=ChatResponse),
            EventDoc.from_handler("join", "/chat", h2, Dependant(h2)),
        ]

        schema = build_schema(registry, title="Test API", version="0.1.0")

        assert schema["title"] == "Test API"
        assert schema["version"] == "0.1.0"
        assert "/" in schema["namespaces"]
        assert "/chat" in schema["namespaces"]
        assert len(schema["namespaces"]["/"]["events"]) == 1
        assert len(schema["namespaces"]["/chat"]["events"]) == 1
        assert schema["namespaces"]["/"]["events"][0]["event"] == "chat"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_docs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fastapi_sio_di.docs'`

- [ ] **Step 3: Implement EventDoc and schema generation**

```python
# fastapi_sio_di/docs.py
"""Socket.IO event documentation: metadata collection and JSON Schema generation."""

import inspect
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from pydantic import BaseModel

from .dependencies import Dependant


# Mapping of Python primitive types to JSON Schema types
_PRIMITIVE_TYPE_MAP: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    dict: "object",
    list: "array",
}


@dataclass
class EventDoc:
    """Metadata for a single registered Socket.IO event handler."""

    event: str
    namespace: str
    handler: Callable
    dependant: Dependant
    summary: Optional[str]
    description: Optional[str]
    response_model: Optional[type]
    is_connect: bool
    is_disconnect: bool

    @classmethod
    def from_handler(
        cls,
        event: str,
        namespace: str,
        handler: Callable,
        dependant: Dependant,
        response_model: Optional[type] = None,
    ) -> "EventDoc":
        """Create an EventDoc by inspecting the handler function."""
        # Extract docstring
        raw_doc = inspect.getdoc(handler)
        summary = None
        description = None
        if raw_doc:
            lines = raw_doc.strip().splitlines()
            summary = lines[0].strip()
            description = raw_doc.strip()

        # Infer response_model from return annotation if not provided
        if response_model is None:
            hints = inspect.get_annotations(handler)
            ret = hints.get("return")
            if ret is not None and ret is not type(None):
                response_model = ret

        return cls(
            event=event,
            namespace=namespace,
            handler=handler,
            dependant=dependant,
            summary=summary,
            description=description,
            response_model=response_model,
            is_connect=(event == "connect"),
            is_disconnect=(event == "disconnect"),
        )


def _type_to_schema(annotation: type) -> Optional[dict[str, Any]]:
    """Convert a type annotation to a JSON Schema dict."""
    if annotation is inspect.Parameter.empty or annotation is None:
        return None
    if inspect.isclass(annotation) and issubclass(annotation, BaseModel):
        return annotation.model_json_schema()
    if annotation in _PRIMITIVE_TYPE_MAP:
        return {"type": _PRIMITIVE_TYPE_MAP[annotation]}
    return None


def build_event_schema(doc: EventDoc) -> dict[str, Any]:
    """Build the JSON schema dict for a single event."""
    # Request schema from unknown_params (data payload)
    request_schema = None
    if doc.dependant.unknown_params:
        _name, param = doc.dependant.unknown_params[0]
        request_schema = _type_to_schema(param.annotation)

    # Response schema
    response_schema = None
    if doc.response_model is not None:
        response_schema = _type_to_schema(doc.response_model)

    # Params list
    params: list[dict[str, str]] = []
    for name, _annotation in doc.dependant.special_params.items():
        params.append({"name": name, "type": _annotation.__name__, "kind": "special"})
    for name, param in doc.dependant.unknown_params:
        type_name = (
            param.annotation.__name__
            if hasattr(param.annotation, "__name__")
            else str(param.annotation)
        )
        params.append({"name": name, "type": type_name, "kind": "payload"})
    for name in doc.dependant.dependencies:
        params.append({"name": name, "type": "Depends", "kind": "dependency"})

    return {
        "event": doc.event,
        "summary": doc.summary,
        "description": doc.description,
        "direction": "client_to_server",
        "is_connect": doc.is_connect,
        "is_disconnect": doc.is_disconnect,
        "request_schema": request_schema,
        "response_schema": response_schema,
        "params": params,
    }


def build_schema(
    registry: list[EventDoc],
    title: str = "Socket.IO API",
    version: str = "1.0.0",
) -> dict[str, Any]:
    """Build the full schema dict grouped by namespace."""
    namespaces: dict[str, dict[str, Any]] = {}
    for doc in registry:
        ns = doc.namespace
        if ns not in namespaces:
            namespaces[ns] = {"events": []}
        namespaces[ns]["events"].append(build_event_schema(doc))

    return {
        "title": title,
        "version": version,
        "namespaces": namespaces,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_docs.py -v`
Expected: All 10 tests PASS

- [ ] **Step 5: Commit**

```bash
git add fastapi_sio_di/docs.py tests/test_docs.py
git commit -m "feat(docs): add EventDoc dataclass and schema generation"
```

---

### Task 2: Integrate event registry into AsyncServer

**Files:**
- Modify: `fastapi_sio_di/async_server.py:39-85` (the `on()` method)
- Test: `tests/test_docs.py` (append new test class)

- [ ] **Step 1: Write failing tests for event registry in AsyncServer**

Append to `tests/test_docs.py`:

```python
# --- AsyncServer integration ---

from fastapi_sio_di import AsyncServer


class TestAsyncServerRegistry:
    def test_on_decorator_populates_registry(self):
        sio = AsyncServer()

        @sio.on("chat")
        async def handle_chat(sid: SID, data: ChatMessage):
            """Chat handler."""
            pass

        assert len(sio._event_registry) == 1
        doc = sio._event_registry[0]
        assert doc.event == "chat"
        assert doc.namespace == "/"
        assert doc.summary == "Chat handler."

    def test_on_with_response_model(self):
        sio = AsyncServer()

        @sio.on("chat", response_model=ChatResponse)
        async def handle_chat(sid: SID, data: ChatMessage):
            pass

        doc = sio._event_registry[0]
        assert doc.response_model is ChatResponse

    def test_on_with_namespace(self):
        sio = AsyncServer()

        @sio.on("join", namespace="/chat")
        async def handle_join(sid: SID):
            pass

        doc = sio._event_registry[0]
        assert doc.namespace == "/chat"

    def test_on_response_model_from_return_type(self):
        sio = AsyncServer()

        @sio.on("chat")
        async def handle_chat(sid: SID) -> ChatResponse:
            pass

        doc = sio._event_registry[0]
        assert doc.response_model is ChatResponse

    def test_multiple_events_registered(self):
        sio = AsyncServer()

        @sio.on("chat")
        async def h1(sid: SID):
            pass

        @sio.on("join", namespace="/room")
        async def h2(sid: SID):
            pass

        assert len(sio._event_registry) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_docs.py::TestAsyncServerRegistry -v`
Expected: FAIL — `AttributeError: 'AsyncServer' object has no attribute '_event_registry'`

- [ ] **Step 3: Modify AsyncServer to collect EventDoc on registration**

In `fastapi_sio_di/async_server.py`:

1. Add import at top:
```python
from .docs import EventDoc
```

2. In `__init__`, add after `self.dependency_overrides`:
```python
self._event_registry: list[EventDoc] = []
```

3. Change `on()` signature to accept `response_model`:
```python
def on(
    self,
    event: str,
    handler: Optional[Callable] = None,
    namespace: Optional[str] = None,
    response_model: Optional[type] = None,
) -> Callable:
```

4. Inside the `decorator` function, after `dependant = Dependant(func)`, add:
```python
event_doc = EventDoc.from_handler(
    event=event,
    namespace=namespace or "/",
    handler=func,
    dependant=dependant,
    response_model=response_model,
)
self._event_registry.append(event_doc)
```

- [ ] **Step 4: Run all tests to verify nothing is broken**

Run: `pytest tests/ -v`
Expected: All tests PASS (both existing and new)

- [ ] **Step 5: Commit**

```bash
git add fastapi_sio_di/async_server.py tests/test_docs.py
git commit -m "feat(docs): integrate event registry into AsyncServer.on()"
```

---

### Task 3: setup_docs() route registration

**Files:**
- Modify: `fastapi_sio_di/docs.py` (add `setup_docs` function)
- Test: `tests/test_docs.py` (append new test class)

- [ ] **Step 1: Write failing tests for setup_docs route registration**

Append to `tests/test_docs.py`:

```python
from starlette.testclient import TestClient


class TestSetupDocs:
    def _create_app_with_docs(self, **kwargs):
        """Helper: create a FastAPI app with sio docs mounted."""
        from starlette.applications import Starlette

        sio = AsyncServer()

        @sio.on("chat", response_model=ChatResponse)
        async def handle_chat(sid: SID, data: ChatMessage):
            """Process chat messages."""
            pass

        @sio.on("join", namespace="/room")
        async def handle_join(sid: SID):
            """Join a room."""
            pass

        app = Starlette()
        sio.setup_docs(app, **kwargs)
        return app, sio

    def test_schema_endpoint_returns_json(self):
        app, sio = self._create_app_with_docs()
        client = TestClient(app)

        resp = client.get("/sio-docs/schema")
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Socket.IO API"
        assert "/" in data["namespaces"]
        assert "/room" in data["namespaces"]
        assert len(data["namespaces"]["/"]["events"]) == 1
        assert data["namespaces"]["/"]["events"][0]["event"] == "chat"

    def test_docs_page_returns_html(self):
        app, sio = self._create_app_with_docs()
        client = TestClient(app)

        resp = client.get("/sio-docs")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "Socket.IO API" in resp.text

    def test_custom_path(self):
        app, sio = self._create_app_with_docs(path="/my-docs")
        client = TestClient(app)

        assert client.get("/my-docs").status_code == 200
        assert client.get("/my-docs/schema").status_code == 200

    def test_custom_title_and_version(self):
        app, sio = self._create_app_with_docs(title="My API", version="2.0.0")
        client = TestClient(app)

        data = client.get("/sio-docs/schema").json()
        assert data["title"] == "My API"
        assert data["version"] == "2.0.0"

        html = client.get("/sio-docs").text
        assert "My API" in html
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_docs.py::TestSetupDocs -v`
Expected: FAIL — `AttributeError: 'AsyncServer' object has no attribute 'setup_docs'`

- [ ] **Step 3: Implement setup_docs in docs.py and expose on AsyncServer**

Add to the bottom of `fastapi_sio_di/docs.py`:

```python
import json
from pathlib import Path
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route


def _load_template() -> str:
    """Load the HTML template from the templates directory."""
    template_path = Path(__file__).parent / "templates" / "docs.html"
    return template_path.read_text(encoding="utf-8")


def setup_docs(
    sio: Any,
    app: Any,
    path: str = "/sio-docs",
    title: str = "Socket.IO API",
    version: str = "1.0.0",
) -> None:
    """Register docs routes on the given Starlette/FastAPI app."""
    # Strip trailing slash for consistent path handling
    path = path.rstrip("/")

    async def schema_endpoint(request: Request) -> JSONResponse:
        schema = build_schema(sio._event_registry, title=title, version=version)
        return JSONResponse(schema)

    async def docs_endpoint(request: Request) -> HTMLResponse:
        template = _load_template()
        html = template.replace("{{title}}", title).replace("{{schema_url}}", f"{path}/schema")
        return HTMLResponse(html)

    app.routes.insert(0, Route(f"{path}/schema", schema_endpoint))
    app.routes.insert(0, Route(path, docs_endpoint))
```

Add to `fastapi_sio_di/async_server.py` — a new method on `AsyncServer`:

```python
def setup_docs(
    self,
    app,
    path: str = "/sio-docs",
    title: str = "Socket.IO API",
    version: str = "1.0.0",
) -> None:
    """Mount interactive Socket.IO API documentation on the given app."""
    from .docs import setup_docs as _setup_docs
    _setup_docs(self, app, path=path, title=title, version=version)
```

- [ ] **Step 4: Create a minimal HTML template placeholder**

Create `fastapi_sio_di/templates/docs.html` with a minimal placeholder (will be replaced in Task 4):

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{{title}}</title>
</head>
<body>
<h1>{{title}}</h1>
<p>Loading docs from <code>{{schema_url}}</code>...</p>
<div id="app"></div>
<script>
const SCHEMA_URL = "{{schema_url}}";
fetch(SCHEMA_URL).then(r => r.json()).then(data => {
  document.getElementById("app").textContent = JSON.stringify(data, null, 2);
});
</script>
</body>
</html>
```

- [ ] **Step 5: Add `starlette` dependency note**

The project already depends on `python-socketio` which depends on starlette-like ASGI patterns. The tests use `starlette.testclient`. Add `starlette` to dev dependencies in `pyproject.toml`:

```toml
[dependency-groups]
dev = [
    "fastapi>=0.128.0",
    "starlette>=0.45.0",
    "uvicorn>=0.40.0",
    "ruff>=0.15.9",
    "ty>=0.0.28",
    "pytest>=9.0.2",
    "pytest-asyncio>=1.3.0",
    "httpx>=0.28.0",
]
```

Run: `uv sync`

- [ ] **Step 6: Run all tests**

Run: `pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add fastapi_sio_di/docs.py fastapi_sio_di/async_server.py fastapi_sio_di/templates/docs.html pyproject.toml uv.lock
git commit -m "feat(docs): add setup_docs() route registration and schema endpoint"
```

---

### Task 4: HTML template — accordion layout with light theme

**Files:**
- Create: `fastapi_sio_di/templates/docs.html` (replace placeholder)

- [ ] **Step 1: Write the complete HTML template**

Replace `fastapi_sio_di/templates/docs.html` with the full implementation. The template must:

1. **Header bar**: title, version badge
2. **Connection bar**: server URL input (default `window.location.origin`), namespace dropdown, connect/disconnect button, status indicator
3. **Accordion body**: fetch `{{schema_url}}`, group events by namespace, render each as a collapsible card
4. **Event card collapsed**: type badge (EMIT green `#198754` / CONNECT orange `#fd7e14` / DISCONNECT red `#dc3545`) + event name + summary
5. **Event card expanded**: request schema + response schema side-by-side, params table
6. **Try-it-out panel** (inside expanded card): JSON textarea (auto-populated from request schema), Send button, Clear log button, event log div
7. **Light theme** colors: background `#f8f9fa`, cards `#fff` border `#dee2e6`, primary `#0d6efd`
8. **JS logic**:
   - `renderSchema(data)`: build DOM from fetched schema JSON
   - `toggleAccordion(el)`: expand/collapse event cards
   - `connectSocket(url, namespace)`: create `io(url, {path, ...})` connection
   - `sendEvent(event, payload)`: emit via socket, log to event log
   - `addLog(direction, type, event, data)`: append to event log with timestamp
9. **CDN**: `<script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>`

The template uses `{{title}}` and `{{schema_url}}` as placeholders replaced by `setup_docs()`.

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{title}}</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f8f9fa; color: #212529; }

  /* Header */
  .header { background: #fff; border-bottom: 1px solid #dee2e6; padding: 16px 24px; display: flex; align-items: center; gap: 12px; }
  .header h1 { font-size: 20px; font-weight: 600; }
  .header .version { background: #e9ecef; color: #495057; padding: 2px 8px; border-radius: 4px; font-size: 12px; }

  /* Connection bar */
  .conn-bar { background: #fff; border-bottom: 1px solid #dee2e6; padding: 10px 24px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .conn-bar label { font-size: 13px; color: #6c757d; }
  .conn-bar input, .conn-bar select { font-size: 13px; padding: 4px 8px; border: 1px solid #dee2e6; border-radius: 4px; background: #f8f9fa; }
  .conn-bar input { flex: 1; min-width: 200px; }
  .conn-bar select { min-width: 120px; }
  .conn-btn { font-size: 13px; padding: 4px 14px; border: none; border-radius: 4px; cursor: pointer; color: #fff; }
  .conn-btn.connect { background: #198754; }
  .conn-btn.disconnect { background: #dc3545; }
  .conn-status { display: flex; align-items: center; gap: 4px; font-size: 12px; }
  .conn-dot { width: 8px; height: 8px; border-radius: 50%; }
  .conn-dot.on { background: #198754; }
  .conn-dot.off { background: #dc3545; }

  /* Main content */
  .content { max-width: 960px; margin: 24px auto; padding: 0 16px; }

  /* Namespace group */
  .ns-group { margin-bottom: 20px; }
  .ns-title { font-size: 14px; font-weight: 600; color: #495057; background: #e9ecef; padding: 8px 12px; border-radius: 4px 4px 0 0; border: 1px solid #dee2e6; cursor: pointer; display: flex; align-items: center; gap: 6px; }
  .ns-title .arrow { transition: transform 0.2s; font-size: 10px; color: #6c757d; }
  .ns-title.collapsed .arrow { transform: rotate(-90deg); }
  .ns-body { border: 1px solid #dee2e6; border-top: none; border-radius: 0 0 4px 4px; }
  .ns-body.hidden { display: none; }

  /* Event card */
  .event-card { border-bottom: 1px solid #e9ecef; }
  .event-card:last-child { border-bottom: none; }
  .event-header { padding: 10px 12px; display: flex; align-items: center; gap: 8px; cursor: pointer; background: #fff; }
  .event-header:hover { background: #f8f9fa; }
  .event-header .arrow { font-size: 10px; color: #6c757d; transition: transform 0.2s; }
  .event-header.expanded .arrow { transform: rotate(90deg); }
  .event-badge { padding: 2px 8px; border-radius: 3px; font-size: 10px; font-weight: 600; color: #fff; text-transform: uppercase; }
  .badge-emit { background: #198754; }
  .badge-connect { background: #fd7e14; }
  .badge-disconnect { background: #dc3545; }
  .event-name { font-weight: 600; font-size: 14px; }
  .event-summary { color: #6c757d; font-size: 13px; margin-left: auto; }

  /* Event detail */
  .event-detail { display: none; padding: 12px; background: #fff; border-top: 1px solid #e9ecef; }
  .event-detail.open { display: block; }
  .schema-row { display: flex; gap: 16px; margin-bottom: 12px; }
  .schema-col { flex: 1; }
  .schema-label { font-size: 11px; text-transform: uppercase; color: #6c757d; margin-bottom: 4px; font-weight: 600; }
  .schema-box { background: #f8f9fa; border: 1px solid #e9ecef; border-radius: 4px; padding: 10px; font-family: "SF Mono", Monaco, Consolas, monospace; font-size: 12px; white-space: pre-wrap; word-break: break-word; }

  /* Try it out */
  .tryout { background: #f1f3f5; border-top: 1px solid #e9ecef; padding: 12px; border-radius: 0 0 4px 4px; margin-top: 8px; }
  .tryout-title { font-size: 12px; font-weight: 600; color: #0d6efd; margin-bottom: 8px; }
  .tryout label { font-size: 11px; color: #6c757d; display: block; margin-bottom: 4px; }
  .tryout textarea { width: 100%; min-height: 80px; font-family: "SF Mono", Monaco, Consolas, monospace; font-size: 12px; padding: 8px; border: 1px solid #dee2e6; border-radius: 4px; resize: vertical; background: #fff; }
  .tryout-actions { display: flex; gap: 8px; margin: 8px 0; }
  .btn { font-size: 12px; padding: 4px 14px; border: none; border-radius: 4px; cursor: pointer; }
  .btn-primary { background: #0d6efd; color: #fff; }
  .btn-secondary { background: #fff; color: #6c757d; border: 1px solid #dee2e6; }
  .event-log { background: #fff; border: 1px solid #dee2e6; border-radius: 4px; padding: 8px; font-family: "SF Mono", Monaco, Consolas, monospace; font-size: 11px; max-height: 200px; overflow-y: auto; min-height: 40px; }
  .log-entry { margin-bottom: 3px; line-height: 1.4; }
  .log-time { color: #adb5bd; }
  .log-out { color: #198754; }
  .log-in { color: #fd7e14; }
  .log-event-name { color: #6c757d; }
  .log-data { color: #495057; }
  .log-type { color: #0d6efd; }
  .log-type-event { color: #dc3545; }

  /* Params table */
  .params-table { width: 100%; border-collapse: collapse; font-size: 12px; margin-bottom: 8px; }
  .params-table th { text-align: left; padding: 4px 8px; background: #f8f9fa; border: 1px solid #e9ecef; font-weight: 600; color: #6c757d; font-size: 11px; text-transform: uppercase; }
  .params-table td { padding: 4px 8px; border: 1px solid #e9ecef; }
  .params-table .kind { font-size: 10px; padding: 1px 6px; border-radius: 3px; }
  .kind-payload { background: #d1e7dd; color: #0f5132; }
  .kind-special { background: #cff4fc; color: #055160; }
  .kind-dependency { background: #e2e3e5; color: #41464b; }

  .empty-msg { color: #adb5bd; font-style: italic; font-size: 13px; padding: 20px; text-align: center; }
</style>
</head>
<body>

<div class="header">
  <h1>{{title}}</h1>
  <span class="version" id="version-badge"></span>
</div>

<div class="conn-bar">
  <label>Server:</label>
  <input type="text" id="server-url" placeholder="ws://localhost:8000">
  <label>Namespace:</label>
  <select id="ns-select"></select>
  <button class="conn-btn connect" id="conn-btn" onclick="toggleConnection()">Connect</button>
  <div class="conn-status">
    <span class="conn-dot off" id="conn-dot"></span>
    <span id="conn-text">Disconnected</span>
  </div>
</div>

<div class="content" id="app">
  <p class="empty-msg">Loading...</p>
</div>

<script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>
<script>
const SCHEMA_URL = "{{schema_url}}";
let schemaData = null;
let socket = null;

// --- Fetch and render ---
fetch(SCHEMA_URL)
  .then(r => r.json())
  .then(data => {
    schemaData = data;
    document.getElementById("version-badge").textContent = "v" + data.version;
    document.getElementById("server-url").value = window.location.origin;
    populateNamespaces(data);
    renderSchema(data);
  });

function populateNamespaces(data) {
  const sel = document.getElementById("ns-select");
  sel.innerHTML = "";
  for (const ns of Object.keys(data.namespaces)) {
    const opt = document.createElement("option");
    opt.value = ns;
    opt.textContent = ns;
    sel.appendChild(opt);
  }
}

function renderSchema(data) {
  const app = document.getElementById("app");
  app.innerHTML = "";
  for (const [ns, nsData] of Object.entries(data.namespaces)) {
    const group = document.createElement("div");
    group.className = "ns-group";

    const title = document.createElement("div");
    title.className = "ns-title";
    title.innerHTML = '<span class="arrow">▶</span> ' + escapeHtml(ns === "/" ? "/ (default)" : ns);
    title.onclick = function() {
      this.classList.toggle("collapsed");
      this.nextElementSibling.classList.toggle("hidden");
    };

    const body = document.createElement("div");
    body.className = "ns-body";

    for (const evt of nsData.events) {
      body.appendChild(createEventCard(evt, ns));
    }

    group.appendChild(title);
    group.appendChild(body);
    app.appendChild(group);
  }
}

function createEventCard(evt, ns) {
  const card = document.createElement("div");
  card.className = "event-card";

  // Badge
  let badgeClass = "badge-emit";
  let badgeText = "EMIT";
  if (evt.is_connect) { badgeClass = "badge-connect"; badgeText = "CONNECT"; }
  if (evt.is_disconnect) { badgeClass = "badge-disconnect"; badgeText = "DISCONNECT"; }

  // Header
  const header = document.createElement("div");
  header.className = "event-header";
  header.innerHTML = `
    <span class="arrow">▶</span>
    <span class="event-badge ${badgeClass}">${badgeText}</span>
    <span class="event-name">${escapeHtml(evt.event)}</span>
    <span class="event-summary">${escapeHtml(evt.summary || "")}</span>
  `;

  // Detail
  const detail = document.createElement("div");
  detail.className = "event-detail";
  detail.innerHTML = buildDetailHTML(evt, ns);

  header.onclick = function() {
    this.classList.toggle("expanded");
    detail.classList.toggle("open");
  };

  card.appendChild(header);
  card.appendChild(detail);
  return card;
}

function buildDetailHTML(evt, ns) {
  let html = "";

  // Description
  if (evt.description && evt.description !== evt.summary) {
    html += `<p style="margin-bottom:12px;font-size:13px;color:#495057;">${escapeHtml(evt.description)}</p>`;
  }

  // Params table
  if (evt.params && evt.params.length > 0) {
    html += `<table class="params-table"><tr><th>Name</th><th>Type</th><th>Kind</th></tr>`;
    for (const p of evt.params) {
      html += `<tr><td>${escapeHtml(p.name)}</td><td><code>${escapeHtml(p.type)}</code></td><td><span class="kind kind-${p.kind}">${p.kind}</span></td></tr>`;
    }
    html += `</table>`;
  }

  // Schema row
  html += `<div class="schema-row">`;
  html += `<div class="schema-col">`;
  html += `<div class="schema-label">Request${evt.request_schema && evt.request_schema.title ? " — " + escapeHtml(evt.request_schema.title) : ""}</div>`;
  html += `<div class="schema-box">${evt.request_schema ? formatSchema(evt.request_schema) : '<span style="color:#adb5bd;">No payload</span>'}</div>`;
  html += `</div>`;
  html += `<div class="schema-col">`;
  html += `<div class="schema-label">Response${evt.response_schema && evt.response_schema.title ? " — " + escapeHtml(evt.response_schema.title) : ""}</div>`;
  html += `<div class="schema-box">${evt.response_schema ? formatSchema(evt.response_schema) : '<span style="color:#adb5bd;">Not defined</span>'}</div>`;
  html += `</div></div>`;

  // Try it out
  const eventId = ns.replace(/\//g, "_") + "_" + evt.event;
  const example = evt.request_schema ? generateExample(evt.request_schema) : "";
  html += `
    <div class="tryout">
      <div class="tryout-title">🧪 Try it out</div>
      <label>Payload (JSON)</label>
      <textarea id="payload-${eventId}">${escapeHtml(example)}</textarea>
      <div class="tryout-actions">
        <button class="btn btn-primary" onclick="sendEvent('${escapeAttr(ns)}','${escapeAttr(evt.event)}','${eventId}')">Send</button>
        <button class="btn btn-secondary" onclick="clearLog('${eventId}')">Clear log</button>
      </div>
      <label>Event Log</label>
      <div class="event-log" id="log-${eventId}"></div>
    </div>
  `;

  return html;
}

function formatSchema(schema) {
  if (!schema.properties) {
    return escapeHtml(JSON.stringify(schema, null, 2));
  }
  let lines = ["{"];
  const required = schema.required || [];
  const props = Object.entries(schema.properties);
  for (let i = 0; i < props.length; i++) {
    const [key, val] = props[i];
    const type = val.type || "any";
    const req = required.includes(key) ? ' <span style="color:#dc3545;">*required</span>' : ' <span style="color:#adb5bd;">optional</span>';
    lines.push(`  <span style="color:#d63384;">"${escapeHtml(key)}"</span>: <span style="color:#0d6efd;">${escapeHtml(type)}</span>${req}`);
  }
  lines.push("}");
  return lines.join("\n");
}

function generateExample(schema) {
  if (!schema.properties) return "";
  const obj = {};
  for (const [key, val] of Object.entries(schema.properties)) {
    if (val.type === "string") obj[key] = "";
    else if (val.type === "integer" || val.type === "number") obj[key] = 0;
    else if (val.type === "boolean") obj[key] = false;
    else if (val.type === "array") obj[key] = [];
    else if (val.type === "object") obj[key] = {};
    else obj[key] = null;
  }
  return JSON.stringify(obj, null, 2);
}

// --- Connection ---
function toggleConnection() {
  if (socket && socket.connected) {
    socket.disconnect();
  } else {
    const url = document.getElementById("server-url").value;
    const ns = document.getElementById("ns-select").value;
    connectSocket(url, ns);
  }
}

function connectSocket(url, namespace) {
  if (socket) { socket.disconnect(); }
  socket = io(url, { path: "/socket.io", transports: ["websocket", "polling"], forceNew: true, autoConnect: true, ...(namespace !== "/" ? {} : {}), });
  if (namespace !== "/") {
    socket = io(url + namespace, { path: "/socket.io", transports: ["websocket", "polling"], forceNew: true });
  }

  socket.on("connect", () => updateConnStatus(true));
  socket.on("disconnect", () => updateConnStatus(false));
  socket.on("connect_error", (err) => {
    updateConnStatus(false);
    addGlobalLog("in", "error", "connect_error", err.message);
  });

  // Listen for all events for logging
  socket.onAny((event, ...args) => {
    addGlobalLog("in", "event", event, JSON.stringify(args.length === 1 ? args[0] : args));
  });
}

function updateConnStatus(connected) {
  const dot = document.getElementById("conn-dot");
  const text = document.getElementById("conn-text");
  const btn = document.getElementById("conn-btn");
  if (connected) {
    dot.className = "conn-dot on";
    text.textContent = "Connected";
    btn.textContent = "Disconnect";
    btn.className = "conn-btn disconnect";
  } else {
    dot.className = "conn-dot off";
    text.textContent = "Disconnected";
    btn.textContent = "Connect";
    btn.className = "conn-btn connect";
  }
}

// --- Send & Log ---
function sendEvent(ns, event, eventId) {
  if (!socket || !socket.connected) {
    alert("Please connect first.");
    return;
  }
  const textarea = document.getElementById("payload-" + eventId);
  let payload;
  try {
    payload = textarea.value.trim() ? JSON.parse(textarea.value) : undefined;
  } catch (e) {
    alert("Invalid JSON: " + e.message);
    return;
  }
  const logEl = document.getElementById("log-" + eventId);

  addLog(logEl, "out", "emit", event, payload !== undefined ? JSON.stringify(payload) : "");

  if (payload !== undefined) {
    socket.emit(event, payload, (ack) => {
      if (ack !== undefined) {
        addLog(logEl, "in", "ack", event, JSON.stringify(ack));
      }
    });
  } else {
    socket.emit(event, (ack) => {
      if (ack !== undefined) {
        addLog(logEl, "in", "ack", event, JSON.stringify(ack));
      }
    });
  }
}

function addLog(logEl, dir, type, event, data) {
  const now = new Date().toLocaleTimeString("en-GB", { hour12: false });
  const arrow = dir === "out" ? '<span class="log-out">→</span>' : '<span class="log-in">←</span>';
  const typeClass = type === "event" ? "log-type-event" : "log-type";
  const entry = document.createElement("div");
  entry.className = "log-entry";
  entry.innerHTML = `<span class="log-time">${now}</span> ${arrow} <span class="${typeClass}">${escapeHtml(type)}</span> <span class="log-event-name">${escapeHtml(event)}</span> <span class="log-data">${escapeHtml(data || "")}</span>`;
  logEl.appendChild(entry);
  logEl.scrollTop = logEl.scrollHeight;
}

function addGlobalLog(dir, type, event, data) {
  // Add to all visible logs
  document.querySelectorAll(".event-log").forEach(el => {
    addLog(el, dir, type, event, data);
  });
}

function clearLog(eventId) {
  const logEl = document.getElementById("log-" + eventId);
  if (logEl) logEl.innerHTML = "";
}

// --- Helpers ---
function escapeHtml(str) {
  if (!str) return "";
  return String(str).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}
function escapeAttr(str) {
  return String(str).replace(/'/g, "\\'").replace(/"/g, "&quot;");
}
</script>
</body>
</html>
```

- [ ] **Step 2: Verify template loads correctly**

Run: `pytest tests/test_docs.py::TestSetupDocs -v`
Expected: All 4 tests PASS (including HTML content check)

- [ ] **Step 3: Commit**

```bash
git add fastapi_sio_di/templates/docs.html
git commit -m "feat(docs): add full HTML template with accordion layout and Try-it-out"
```

---

### Task 5: Export and final integration

**Files:**
- Modify: `fastapi_sio_di/__init__.py`
- Test: `tests/test_docs.py` (add import test)

- [ ] **Step 1: Write test for public API export**

Append to `tests/test_docs.py`:

```python
class TestPublicAPI:
    def test_eventdoc_importable_from_package(self):
        from fastapi_sio_di import EventDoc
        assert EventDoc is not None

    def test_setup_docs_accessible_on_server(self):
        sio = AsyncServer()
        assert hasattr(sio, "setup_docs")
        assert callable(sio.setup_docs)
```

- [ ] **Step 2: Run tests to verify import fails**

Run: `pytest tests/test_docs.py::TestPublicAPI -v`
Expected: FAIL — `ImportError: cannot import name 'EventDoc'`

- [ ] **Step 3: Add EventDoc to __init__.py exports**

In `fastapi_sio_di/__init__.py`:

```python
from .async_server import AsyncServer
from .docs import EventDoc
from .exceptions import SocketIOValidationError
from .params import SID, Environ


__all__ = ["AsyncServer", "EventDoc", "SID", "Environ", "SocketIOValidationError"]
```

- [ ] **Step 4: Run the full test suite**

Run: `pytest tests/ -v`
Expected: ALL tests PASS

- [ ] **Step 5: Commit**

```bash
git add fastapi_sio_di/__init__.py tests/test_docs.py
git commit -m "feat(docs): export EventDoc and finalize public API"
```

---

### Task 6: Manual integration test with example server

**Files:**
- Modify: `tests/server.py` (add docs setup for manual verification)

- [ ] **Step 1: Update example server to mount docs**

Read current `tests/server.py` and add `sio.setup_docs(app)` and a couple of example handlers with Pydantic models and response_model. This is for manual browser verification only.

```python
# Add to existing tests/server.py, after sio and app setup:
sio.setup_docs(app, title="Example Socket.IO API", version="0.1.0")
```

- [ ] **Step 2: Run example server and verify in browser**

Run: `cd tests && python server.py`
Open: `http://localhost:8000/sio-docs`
Verify:
- Page loads with light theme
- Events grouped by namespace in accordion
- Schema displays correctly
- Can connect and send test events
- Event log shows sent/received messages

- [ ] **Step 3: Commit**

```bash
git add tests/server.py
git commit -m "feat(docs): add docs to example server for manual testing"
```

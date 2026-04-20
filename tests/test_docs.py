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
            response_model=None,
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

        req = schema["request_schema"]
        assert req["title"] == "ChatMessage"
        assert "content" in req["properties"]
        assert "content" in req["required"]

        resp = schema["response_schema"]
        assert resp["title"] == "ChatResponse"
        assert "status" in resp["properties"]

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

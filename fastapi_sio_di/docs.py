"""Socket.IO event documentation: metadata collection and JSON Schema generation."""

import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from pydantic import BaseModel
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from .dependencies import Dependant


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
        raw_doc = inspect.getdoc(handler)
        summary = None
        description = None
        if raw_doc:
            lines = raw_doc.strip().splitlines()
            summary = lines[0].strip()
            description = raw_doc.strip()

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
    if annotation is inspect.Parameter.empty or annotation is None:
        return None
    if inspect.isclass(annotation) and issubclass(annotation, BaseModel):
        return annotation.model_json_schema()
    if annotation in _PRIMITIVE_TYPE_MAP:
        return {"type": _PRIMITIVE_TYPE_MAP[annotation]}
    return None


def build_event_schema(doc: EventDoc) -> dict[str, Any]:
    request_schema = None
    if doc.dependant.unknown_params:
        _name, param = doc.dependant.unknown_params[0]
        request_schema = _type_to_schema(param.annotation)

    response_schema = None
    if doc.response_model is not None:
        response_schema = _type_to_schema(doc.response_model)

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
    description: Optional[str] = None,
) -> dict[str, Any]:
    namespaces: dict[str, dict[str, Any]] = {}
    for doc in registry:
        ns = doc.namespace
        if ns not in namespaces:
            namespaces[ns] = {"events": []}
        namespaces[ns]["events"].append(build_event_schema(doc))

    schema: dict[str, Any] = {
        "title": title,
        "version": version,
        "namespaces": namespaces,
    }
    if description:
        schema["description"] = description
    return schema


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
    description: Optional[str] = None,
) -> None:
    """Register docs routes on the given Starlette/FastAPI app."""
    path = path.rstrip("/")

    async def schema_endpoint(request: Request) -> JSONResponse:
        schema = build_schema(sio._event_registry, title=title, version=version, description=description)
        return JSONResponse(schema)

    async def docs_endpoint(request: Request) -> HTMLResponse:
        template = _load_template()
        html = template.replace("{{title}}", title).replace("{{schema_url}}", f"{path}/schema")
        return HTMLResponse(html)

    app.routes.insert(0, Route(f"{path}/schema", schema_endpoint))
    app.routes.insert(0, Route(path, docs_endpoint))

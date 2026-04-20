<div align="center">
  <h1>FastAPI-SIO-DI</h1>
  <span><a href="../README.md">English</a> | 中文</span>
</div>

[![PyPI](https://img.shields.io/pypi/v/fastapi-sio-di.svg)](https://pypi.org/project/fastapi-sio-di/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](https://github.com/GJCoke/fastapi-socketio/blob/main/LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/downloads/)

FastAPI-SIO-DI 是一个为 FastAPI 量身打造的 Socket.IO 集成库。它让你能够以最熟悉的 **FastAPI 风格**（依赖注入、Pydantic 模型）来开发实时 WebSocket 应用。

## 核心特性

*   **原生依赖注入**：在 Socket.IO 事件处理器中直接使用 `Depends`，就像写 HTTP 接口一样。支持 `Annotated[T, Depends()]` 风格。
*   **Pydantic 模型支持**：自动校验和转换客户端发送的 JSON 数据为 Pydantic 对象；发送消息时自动序列化模型。
*   **交互式 API 文档**：自动生成 Swagger 风格的文档 UI，支持实时 Socket.IO 测试 — 调用 `setup_docs()` 即可。
*   **Admin UI 监控**：内置 [Socket.IO Admin UI](https://admin.socket.io/) 支持，实时监控服务器状态。
*   **零侵入集成**：基于 `python-socketio`，完全兼容其原有生态，只需替换 `AsyncServer` 类即可。

## 安装

```bash
pip install fastapi-sio-di
```

## 快速开始

```python
from fastapi import FastAPI, Depends
from fastapi_sio_di import AsyncServer, SID, Environ
from pydantic import BaseModel
import socketio

# 1. 初始化 FastAPI 和 Socket.IO
app = FastAPI()
sio = AsyncServer(async_mode="asgi", cors_allowed_origins="*")
sio_app = socketio.ASGIApp(sio)
app.mount("/socket.io", sio_app)


# 2. 定义 Pydantic 模型
class ChatMessage(BaseModel):
    user: str
    text: str

class Reply(BaseModel):
    text: str
    from_user: str


# 3. 定义依赖项
async def get_current_user(token: str = "anonymous"):
    return {"username": "user_" + token}


# 4. 编写事件处理器
@sio.on("connect")
async def on_connect(sid: SID, environ: Environ, auth: dict):
    print(f"新连接: {sid}, 客户端: {environ.client}")

@sio.on("chat", response_model=Reply)
async def handle_chat(
    sid: SID,
    data: ChatMessage,
    user=Depends(get_current_user),
):
    print(f"收到消息来自 {user['username']}: {data.text}")
    return Reply(text=f"Echo: {data.text}", from_user=user["username"])


# 5. 启用交互式文档和 Admin UI
sio.setup_docs(app, title="My Socket.IO API", version="1.0.0")
sio.instrument({"username": "admin", "password": "secret"})
```

运行：

```bash
uvicorn main:app
```

然后打开：
- `http://localhost:8000/sio/docs` — 交互式 API 文档
- `https://admin.socket.io/` — Admin UI（连接到你的服务器）

## API 参考

### AsyncServer

`socketio.AsyncServer` 的直接替换，增加了以下功能：

```python
sio = AsyncServer(async_mode="asgi", cors_allowed_origins="*", serializer="model_dump")
```

| 参数 | 说明 |
|---|---|
| `serializer` | Pydantic 序列化方法名（默认 `model_dump`，回退 `dict`） |
| *其他参数* | 透传给 `socketio.AsyncServer` |

#### `@sio.on(event, namespace, response_model)`

注册事件处理器，支持依赖注入：

```python
@sio.on("message", response_model=Reply)
async def handle(sid: SID, data: MyModel, db=Depends(get_db)):
    ...
```

`response_model` 参数启用返回值序列化，并出现在生成的文档 schema 中。

#### `sio.setup_docs(app, path, title, version)`

挂载交互式 API 文档：

```python
sio.setup_docs(app, path="/sio/docs", title="My API", version="1.0.0")
```

会创建两个端点：
- `{path}` — 带实时测试功能的交互式 HTML 文档
- `{path}/schema` — JSON Schema 端点

#### `sio.instrument(auth)`

启用 [Socket.IO Admin UI](https://admin.socket.io/) 集成：

```python
sio.instrument({"username": "admin", "password": "secret"})
```

#### `sio.dependency_overrides`

在测试中覆盖依赖项，与 FastAPI 相同的模式：

```python
sio.dependency_overrides[get_db] = lambda: mock_db
```

### 类型标记

#### `SID`

注入当前连接的 Session ID：

```python
@sio.on("event")
async def handler(sid: SID):
    print(f"Session: {sid}")  # sid 是 str 类型
```

#### `Environ`

注入握手环境信息，提供便捷的属性访问：

```python
@sio.on("connect")
async def on_connect(sid: SID, environ: Environ):
    environ.scope         # ASGI scope 字典
    environ.headers       # HTTP 请求头字典
    environ.client        # (host, port) 元组
    environ.path          # 请求路径
    environ.query_string  # 原始查询字符串
    environ.http_version  # 例如 "1.1"
```

### 依赖注入

完整支持 FastAPI 风格的 `Depends`，包括：

**标准风格：**
```python
@sio.on("event")
async def handler(db=Depends(get_db)):
    ...
```

**Annotated 风格：**
```python
from typing import Annotated

DB = Annotated[Session, Depends(get_db)]

@sio.on("event")
async def handler(db: DB):
    ...
```

**生成器依赖**（自动生命周期管理）：
```python
async def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        await db.close()
```

**依赖链**：依赖项可以依赖其他依赖项，支持缓存以避免重复解析。

### Connect 处理器

`connect` 事件处理器可接收客户端发送的 `auth` 数据：

```python
@sio.on("connect")
async def on_connect(sid: SID, environ: Environ, auth: dict):
    if not validate_token(auth.get("token")):
        raise ConnectionRefusedError("无效的 token")
```

### 错误处理

当 Pydantic 校验失败时，会抛出 `SocketIOValidationError`：

```python
from fastapi_sio_di import SocketIOValidationError

try:
    ...
except SocketIOValidationError as e:
    print(e.errors)      # 校验错误列表
    print(e.model_name)  # Pydantic 模型名称
```

## 环境要求

- Python 3.10+
- `python-socketio >= 5.16.1`

## 贡献

欢迎提交 Issue 和 Pull Request！

## 许可证

[MIT License](../LICENSE)

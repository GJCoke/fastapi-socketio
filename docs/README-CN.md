# FastAPI-SIO

**FastAPI-SIO** 是一个为 FastAPI 量身打造的 Socket.IO 集成库。它让你能够以最熟悉的 **FastAPI 风格**（依赖注入、Pydantic 模型）来开发实时 WebSocket 应用。

## 核心特性

*   **️原生依赖注入**：在 Socket.IO 事件处理器中直接使用 `Depends`，就像写 HTTP 接口一样。
*   **Pydantic 模型支持**：自动校验和转换客户端发送的 JSON 数据为 Pydantic 对象；发送消息时自动序列化模型。
*   **零侵入集成**：基于 `python-socketio`，完全兼容其原有生态，只需替换 `AsyncServer` 类即可。

## 安装

```bash
pip install fastapi-sio
```

## 快速开始
### 1. 基础示例
创建一个 `main.py` 文件：

```python
from fastapi import FastAPI, Depends
from fastapi_sio_di import AsyncServer, SID, Environ
from pydantic import BaseModel
import socketio

# 1. 初始化 FastAPI 和 Socket.IO
app = FastAPI()
# 使用 fastapi_sio_di 提供的 AsyncServer
sio = AsyncServer(async_mode="asgi", cors_allowed_origins="*")
sio_app = socketio.ASGIApp(sio)
app.mount("/socket.io", sio_app)


# 2. 定义 Pydantic 模型
class ChatMessage(BaseModel):
    user: str
    text: str


# 3. 定义依赖项 (Dependency)
async def get_current_user(token: str):
    # 这里可以进行数据库查询或鉴权
    return {"username": "user_" + token}


# 4. 编写事件处理器
@sio.on("connect")
async def on_connect(sid: SID, environ: Environ):
    print(f"新连接: {sid}")
    # 你可以从 environ 中获取 header，例如鉴权 token
    # print(environ.get('HTTP_AUTHORIZATION'))


@sio.on("chat")
async def handle_chat(
    sid: SID,
    data: ChatMessage,  # 自动校验并转换 Pydantic 模型
    token: str = "default_token",  # 支持普通参数
    user=Depends(get_current_user),  # 支持 FastAPI 依赖注入！
):
    print(f"收到消息: {data.text} 来自 {user['username']}")

    # 直接发送 Pydantic 模型，会自动序列化为 JSON
    await sio.emit("reply", data, room=sid)


```
### 2. 运行
```bash
uvicorn main:app
```
现在你可以使用任何 Socket.IO 客户端连接到 http://localhost:8000。

## 进阶用法
### 依赖注入 (Dependency Injection)
`FastAPI-SIO` 的最大亮点是支持 `Depends`。这意味着你可以复用现有的 FastAPI 依赖逻辑（如数据库会话、用户鉴权）。

```python
from sqlalchemy.orm import Session
from fastapi import Depends
from app.db import get_db


@sio.on("create_item")
async def create_item(data: ItemCreate, db: Session = Depends(get_db)):
    # db 会话会自动创建并在事件处理结束后关闭
    new_item = Item(**data.dict())
    db.add(new_item)
    db.commit()
```

### 获取上下文信息
使用类型注解 和 `Environ` 来获取 Socket.IO 的上下文信息。 `SID`
- : 当前连接的 Session ID。 `sid: SID`
- : 握手时的环境信息（包含 Headers 等）。 `environ: Environ`
```python
@sio.on("connect")
async def connect(sid: SID, environ: Environ):
    # 获取客户端 IP
    client_ip = environ.get("REMOTE_ADDR")
    print(f"Client {sid} connected from {client_ip}")
```
### 序列化配置
在初始化 `AsyncServer` 时，你可以指定序列化 Pydantic 模型的方法名（默认为 `model_dump` 或 `dict`）。

```python
# 如果你的模型有一个自定义的 .json() 方法
sio = AsyncServer(serializer="json")
```

## 贡献
欢迎提交 Issue 和 Pull Request！

## 许可证
[MIT License](../LICENSE)
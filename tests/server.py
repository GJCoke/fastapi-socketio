from fastapi import FastAPI, Depends
from fastapi_sio_di.async_server import AsyncServer
from fastapi_sio_di import SID, Environ
import socketio
from typing import Annotated

from pydantic import BaseModel

app = FastAPI()
# 现在你可以直接像使用普通 AsyncServer 一样初始化它
sio = AsyncServer(async_mode="asgi", cors_allowed_origins=["*"])
sio_app = socketio.ASGIApp(sio)
app.mount("/socket.io", sio_app)


class MyBase(BaseModel):
    pass


class Message(MyBase):
    msg: str


async def test1():
    return "test1"


async def test2(test12: Annotated[str, Depends(test1)]):
    return test12, "test2"


async def get_token(test22: tuple[str, str] = Depends(test2)):
    # 依赖项现在能从握手信息中拿到 header
    return test22


@sio.on("connect")
async def on_connect(environ: Environ, sid: SID, auth):
    print(f"Connected with {sid} {environ} {auth}")
    return True


@sio.on("disconnect")
async def on_disconnect(sid: SID, data: str):
    print("Disconnected", sid, data)


@sio.on("message")
async def handle_message(data: Message, test=Depends(get_token)):
    print(f"User with token sent: {data, test}")
    await sio.emit("reply", {"status": "ok"})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, port=8004)

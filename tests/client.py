import asyncio
import socketio

sio = socketio.AsyncClient(
    logger=True,
    engineio_logger=True,
)


@sio.event
async def connect():
    print("✅ 已成功连接到服务器")


@sio.event
async def disconnect():
    print("❌ 与服务器断开连接")


@sio.on("reply")
async def on_reply(data):
    print(f"📩 收到服务器回执: {data}")


async def main():
    headers = {"Authorization": "Bearer my-secret-token"}

    print("正在尝试连接到服务器...")

    await sio.connect(
        "http://127.0.0.1:12345",
        # headers=headers,
        auth={"token": "my-secret-token"},
        socketio_path="",
    )

    test_data = {"msg": "Hello FastAPI-SIO!"}
    print(f"📤 发送消息: {test_data}")
    await sio.emit("message", test_data)

    await asyncio.sleep(2)
    await sio.disconnect()


if __name__ == "__main__":
    asyncio.run(main())

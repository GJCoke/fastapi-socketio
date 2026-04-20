# Socket.IO API Docs UI — 设计规格

## 概述

为 `fastapi-sio-di` 项目新增类似 Swagger UI 的交互式文档页面，自动展示所有注册的 Socket.IO 事件及其入参、出参 schema，并提供在线测试功能。

### 目标用户

所有开发者（前端消费者 + 后端维护者），需要快速查阅事件签名、调试测试。

### 核心体验

- 开发者只需正常编写带类型注解的事件处理器，文档自动生成
- 访问 `/sio-docs` 即可查看所有事件，无需额外配置
- 页面内可直接连接服务器、发送事件、查看响应

---

## 1. 事件注册表与元数据收集

### 1.1 EventDoc 数据类

```python
@dataclass
class EventDoc:
    event: str                      # 事件名，如 "chat"
    namespace: str                  # namespace，默认 "/"
    handler: Callable               # 原始处理函数
    dependant: Dependant            # 已有的 DI 分析对象
    summary: str | None             # 简短描述（docstring 第一行）
    description: str | None         # 详细描述（完整 docstring）
    response_model: type | None     # 出参模型
    is_connect: bool                # 是否 connect 事件
    is_disconnect: bool             # 是否 disconnect 事件
```

### 1.2 元数据收集时机

在 `AsyncServer.on()` 装饰器中，创建 `Dependant` 对象后，同时构建 `EventDoc` 并存入 `self._event_registry: list[EventDoc]`。

### 1.3 入参 schema 提取

- 从 `Dependant.unknown_params` 获取数据参数（客户端发送的 payload）
- Pydantic BaseModel 类型：通过 `model.model_json_schema()` 生成 JSON Schema
- 基础类型（str, int, dict 等）：直接映射为简单 JSON Schema

### 1.4 出参 schema 提取（优先级）

1. `@sio.on("chat", response_model=ChatResponse)` — 装饰器显式声明，最高优先级
2. `async def handle(...) -> ChatResponse` — 返回值类型注解
3. 无出参信息 — 标记为 "未定义"

Pydantic BaseModel 通过 `model_json_schema()` 生成 schema，基础类型直接映射。

### 1.5 装饰器 API 扩展

`@sio.on()` 新增 `response_model` 可选参数：

```python
@sio.on("chat", response_model=ChatResponse)
async def handle_chat(sid: SID, data: ChatMessage):
    """处理聊天消息"""
    ...
```

docstring 第一行自动提取为 `summary`，完整内容作为 `description`。

---

## 2. JSON Schema Endpoint

### 2.1 路径

`GET {docs_path}/schema`（默认 `/sio-docs/schema`）

### 2.2 响应结构

```json
{
  "title": "Socket.IO API",
  "version": "1.0.0",
  "namespaces": {
    "/": {
      "events": [
        {
          "event": "chat",
          "summary": "处理聊天消息",
          "description": "处理聊天消息\n\n接收客户端发送的聊天内容...",
          "direction": "client_to_server",
          "is_connect": false,
          "is_disconnect": false,
          "request_schema": {
            "title": "ChatMessage",
            "type": "object",
            "properties": {
              "content": {"type": "string"},
              "room": {"type": "string"}
            },
            "required": ["content"]
          },
          "response_schema": {
            "title": "ChatResponse",
            "type": "object",
            "properties": {
              "status": {"type": "string"},
              "timestamp": {"type": "number"}
            }
          },
          "params": [
            {"name": "data", "type": "ChatMessage", "kind": "payload"},
            {"name": "sid", "type": "SID", "kind": "special"}
          ]
        }
      ]
    }
  }
}
```

### 2.3 字段说明

- `direction`: 固定为 `client_to_server`（通过 `@sio.on` 注册的事件）。预留扩展空间。
- `request_schema` / `response_schema`: 标准 JSON Schema 格式。
- `params`: 完整参数列表，DI 依赖项仅展示名称和类型，不暴露内部 schema。

---

## 3. 前端文档页面

### 3.1 布局

**手风琴折叠布局（Swagger 经典风格）：**

- 单栏布局，无侧边栏
- Namespace 作为分组标题
- 每个事件为一个可展开/折叠的卡片
- 折叠状态：显示事件类型标签（EMIT / CONNECT / DISCONNECT）+ 事件名 + summary
- 展开状态：显示完整 schema + Try it out 面板

### 3.2 主题

**浅色（Light）主题**，配色参考：

- 背景：`#f8f9fa`
- 卡片：`#fff`，边框 `#dee2e6`
- 事件类型标签颜色：
  - EMIT: `#198754`（绿色）
  - CONNECT: `#fd7e14`（橙色）
  - DISCONNECT: `#dc3545`（红色）
- 主色调：`#0d6efd`（蓝色）
- 代码区域：`#f8f9fa` 背景 + `#e9ecef` 边框

### 3.3 技术栈

- 纯 HTML + Vanilla JS，零构建依赖
- socket.io-client 通过 CDN 引入（用于在线测试）
- 模板作为 Python 字符串内嵌在模块中

### 3.4 事件分组

按 namespace 自动分组，namespace 作为可折叠的分组标题。

---

## 4. 在线测试（Try it out）

### 4.1 全局连接栏

页面顶部固定的连接管理栏：

- Server URL 输入框（默认当前页面的 host）
- Namespace 选择（从 schema 中获取）
- Connect / Disconnect 按钮
- 连接状态指示灯（绿色已连接 / 红色未连接）

连接按 namespace 级别管理，切换 namespace 需重新连接。

### 4.2 JSON 编辑器

- 展开事件卡片后显示在 schema 下方
- 根据 request_schema 自动生成示例 JSON payload
- 用户可直接编辑 JSON 文本
- textarea 实现，足够简单可靠

### 4.3 发送与响应

- **Send 按钮**：通过 socket.io-client 发送事件，支持 ack 回调捕获
- **Clear log 按钮**：清空当前事件的日志

### 4.4 Event Log

实时滚动日志面板，记录：

- `→ emit`：发出的事件（绿色箭头）
- `← ack`：服务端 ack 响应（橙色箭头）
- `← event`：服务端主动推送的事件（橙色箭头，红色标签）

每条日志包含时间戳 + 方向 + 类型 + 事件名 + JSON 数据。

---

## 5. ASGI 集成

### 5.1 用户 API

```python
from fastapi import FastAPI
from fastapi_sio_di import AsyncServer

sio = AsyncServer()
app = FastAPI()

# 方式1：默认配置
sio.setup_docs(app)

# 方式2：自定义
sio.setup_docs(app, path="/sio-docs", title="My Socket.IO API", version="1.0.0")
```

### 5.2 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `app` | FastAPI/Starlette | 必填 | 要挂载的 ASGI 应用 |
| `path` | str | `"/sio-docs"` | 文档页面路径 |
| `title` | str | `"Socket.IO API"` | 文档标题 |
| `version` | str | `"1.0.0"` | API 版本号 |

### 5.3 注册的路由

- `GET {path}` — 返回 HTML 文档页面
- `GET {path}/schema` — 返回 JSON schema 数据

### 5.4 实现方式

通过 Starlette 的 `Route` 直接注册到 `app.routes`，不使用子应用挂载，避免路径前缀问题。

---

## 6. 文件结构

```
fastapi_sio_di/
  docs.py              # EventDoc 数据类 + schema 生成 + setup_docs() + 路由处理
  templates/
    docs.html          # HTML 模板（手风琴布局 + Try it out + light 主题 + JS）
  async_server.py      # 修改：on() 中收集 EventDoc，新增 _event_registry 和 setup_docs()
```

---

## 7. 不在本次范围内

- Server-to-client 事件文档（服务端主动 emit 的事件）— 需要额外的注册机制，后续扩展
- 静态 HTML 导出
- 暗色主题切换
- 认证/授权集成到测试面板
- AsyncAPI 规范导出

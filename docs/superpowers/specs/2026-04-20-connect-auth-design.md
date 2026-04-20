# Connect Auth 弹窗 — 设计规格

## 概述

为 sio-docs UI 的 Connect 流程增加 auth 数据输入能力。当 connect 事件声明了 auth 参数（schema 中存在 `request_schema`）时，点击 Connect 弹出 Auth 弹窗让用户填写 JSON；无 auth 参数时行为不变，直接连接。

### 目标

- 让需要鉴权的 Socket.IO 服务能在 docs 页面内完成连接测试
- 零后端改动，纯前端实现

---

## 1. 流程

1. 用户点击 Connect 按钮
2. 前端在当前 namespace 的 events 中查找 `is_connect === true` 的事件
3. 若该事件有 `request_schema`（即 connect handler 声明了 auth 参数）→ 弹出 Auth 弹窗
4. 若无 `request_schema` → 直接调用 `connectSio(url, ns)` 连接
5. 弹窗内用户填写 auth JSON 后点 **Connect** → 调用 `connectSio(url, ns, authData)`
6. 用户也可点 **Skip** 跳过 auth 直接连接（方便调试不强制鉴权的场景）

---

## 2. 弹窗 UI

### 2.1 结构

- 半透明遮罩层（`rgba(0,0,0,0.3)`），点击遮罩关闭弹窗（取消连接）
- 居中白色卡片，宽度 480px，圆角
- 标题："Connection Authentication"
- 副标题：显示目标 namespace
- `textarea`：预填从 connect 事件的 `request_schema` 通过 `buildExample()` 生成的示例 JSON
- 按钮行：**Connect**（蓝色主按钮）+ **Skip**（灰色次按钮）

### 2.2 交互

- Connect 按钮：解析 textarea 中的 JSON，解析失败 alert 报错不关闭弹窗；成功则关闭弹窗并带 auth 连接
- Skip 按钮：关闭弹窗，不带 auth 直接连接
- 点击遮罩或按 Escape：关闭弹窗，取消连接
- 弹窗打开时 textarea 自动聚焦

---

## 3. 代码变更

### 3.1 仅修改 `fastapi_sio_di/templates/docs.html`

**CSS 新增：**
- `.auth-overlay`：固定定位遮罩层
- `.auth-modal`：居中弹窗卡片
- `.auth-modal textarea`：复用现有 mono 字体和编辑器样式

**JS 修改：**
- `connectSio(url, ns, auth)` 新增第三个参数，传给 `io(url + ns, { transports: [...], auth: auth })`，`auth` 为 `undefined` 时不传该选项
- Connect 按钮 `onclick`：检查 `schemaData` 中当前 namespace 是否有 connect 事件带 `request_schema`
  - 有 → 调用 `showAuthModal(url, ns, schema)` 显示弹窗
  - 无 → 直接 `connectSio(url, ns)`
- 新增 `showAuthModal(url, ns, connectSchema)` 函数：动态创建弹窗 DOM，绑定事件，处理连接
- 新增 `getConnectSchema(ns)` 辅助函数：从 `schemaData.namespaces[ns].events` 中找 `is_connect === true` 的事件并返回其 `request_schema`

### 3.2 后端

无变更。connect 事件的 auth 参数已通过现有 `unknown_params` 机制收集到 `request_schema`。

---

## 4. 不在本次范围

- auth token 的持久化（localStorage 等）
- OAuth / JWT 特定的 UI 流程
- 从 connect handler 的 Depends() 依赖推断 auth 需求
- auth 表单字段自动生成（只提供 JSON 编辑器）

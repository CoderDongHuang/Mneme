# 前端设计

前端使用 React、Vite、React Router、Lucide 和 React Markdown。浏览器只访问 Java Gateway。

## 页面

- `/auth`：深色编辑式品牌页面，登录与注册使用同一表单契约。
- `/chat`：安静的学习工作区，包含会话、资料范围、流式回答、引用与记忆确认。
- `/knowledge`：浅色资料操作台，包含资料库、拖放上传、任务状态和 chunk 统计。
- `/memory`：深色学习画像档案，展示偏好、薄弱点优先级与进度锚点。

## 数据原则

- JWT 保存在 `localStorage` 的 `mneme_auth` 中。
- API 收到 401 时统一清除会话并回到认证页。
- SSE 使用 `fetch + ReadableStream`，因此支持 POST 请求和 `AbortController`。
- 上传后轮询 Java 文档状态，不直接访问 Python task 接口。

## 响应式

全局导航在 760px 以下变为抽屉。聊天会话栏、资料库索引和画像网格分别采用适合本页面的移动布局。

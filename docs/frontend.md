# 前端设计

前端使用 React、Vite、React Router、Lucide 和 React Markdown。浏览器只访问 Java Gateway。

## 页面

- `/auth`：低饱和图书馆画面与简洁表单，包含登录、注册和密码重置。
- `/chat`：安静的学习工作区，包含会话、资料范围、流式回答、引用与记忆确认。
- `/knowledge`：浅色资料操作台，包含资料库、拖放上传、任务状态和 chunk 统计。
- `/memory`：学习画像、长期记忆和确认管理。
- `/workspace`：学习指标、计划、复习、测验和分支。
- `/tasks`、`/recovery`：任务状态与恢复操作。
- `/privacy`、`/operations`、`/analytics`：隐私、运维与学习分析。
- `/profile`、`/settings`：个人资料、密码、外观和偏好。
- `/legal/:document`：隐私政策和服务条款。

所有工作区页面共用低饱和主题变量、侧栏与移动导航；外观设置支持明暗模式。页面可用性以实际浏览器验收为准。

## 数据原则

- JWT 只保存在 Java 设置的 HttpOnly Cookie 中；`localStorage` 的 `mneme_auth` 仅保存非敏感的用户展示信息和登录状态。
- API 收到 401 时统一清除会话并回到认证页。
- SSE 使用 `fetch + ReadableStream`，因此支持 POST 请求和 `AbortController`。
- 上传后轮询 Java 文档状态，不直接访问 Python task 接口。

## 响应式

全局导航在 760px 以下变为抽屉。聊天会话栏、资料库索引和画像网格分别采用适合本页面的移动布局。

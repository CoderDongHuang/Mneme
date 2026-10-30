# 前端设计

前端使用 React、Vite、React Router、Lucide 和 React Markdown。浏览器只访问 Java Gateway。

## 页面

- `/auth`：暖白与低饱和青绿的分栏画面，包含登录、注册、密码显示和密码重置。
- `/chat`：安静的学习工作区，包含会话、资料范围、流式回答、引用与记忆确认。
- `/knowledge`：浅色资料操作台，包含资料库、拖放上传、任务状态和 chunk 统计。
- `/memory`：学习记忆列表、筛选、详情、编辑、确认、归档和删除。
- `/review`：到期日历、计划、翻面卡片、SM-2 评分与进度。
- `/quiz`：生成测验、草稿、问题反馈、提交解释与历史记录。
- `/workspace`：与对话页一致的历史、聊天、引用布局；通过“工具”菜单打开原文阅读、检索调试和会话分支。
- `/tasks`、`/recovery`：任务状态与恢复操作。
- `/privacy`、`/operations`、`/analytics`：隐私、运维与学习分析。
- `/profile`、`/settings`：个人资料、密码/会话、中英文、时区、通知、主题与每用户加密模型配置。
- `/legal/:document`：隐私政策和服务条款。

所有工作区页面共用低饱和主题变量、侧栏与移动导航；外观设置支持明暗模式。页面可用性以实际浏览器验收为准。

统一组件位于 `components/ui.jsx`，包括 PageHeader、StatusPill、SideDrawer、FeedbackBlock、DangerZone 和 Modal。`ReferenceUI.jsx` 提供桌面并排详情、窄屏抽屉、摘要卡和时区日历；`LearningCharts.jsx` 使用真实学习事件绘图并提供可访问的数据表。`layers.css` 固定 legacy/design/reference 层级，参考图布局位于 `reference*.css`，避免以 `!important` 互相覆盖。主题令牌在 `theme.css`，翻译在 `i18n/`，持久偏好由 PreferencesContext 管理。15 个页面模块均延迟加载；原工作台工具单独延迟加载。

## 数据原则

- JWT 只保存在 Java 设置的 HttpOnly Cookie 中；`localStorage` 的 `mneme_auth` 仅保存非敏感的用户展示信息和登录状态。
- API 收到 401 时统一清除会话并回到认证页。
- SSE 使用 `fetch + ReadableStream`，因此支持 POST 请求和 `AbortController`。
- 上传后轮询 Java 文档状态，不直接访问 Python task 接口。
- 轮询由 `useSerialPoll` 串行执行，切换范围后旧结果失效；批量上传逐文件跟踪，不以一个失败中止其他文件。
- 会话切换以请求序号丢弃乱序响应；用户向上阅读时不强制滚底。历史、分支及归档保留引用快照；归档导入的旧文档 ID 不用于导航，避免错链。
- 管理员页面由服务端角色和独立凭证保护，隐藏导航不能代替 API 鉴权。管理员凭证不写入 localStorage。

## 响应式

全局导航和右侧详情在 1100px 及以下变为抽屉；聊天历史在 600px 及以下收起。宽屏对话以 240px 主导航、258px 历史、380px 引用面板为基准，正文占用剩余空间。知识库采用文件表格与并排原文预览，其余参考页面使用摘要、主内容及详情列。窄屏通过按钮打开面板，保留焦点管理和背景隔离。

本轮图片对应、保留功能和验收范围见 [参考图还原记录](FRONTEND_REFERENCE_20261030.md)。认证、个人资料、恢复、管理员和法律页面的专属布局等待独立视觉参考，本轮仅沿用共享外壳。

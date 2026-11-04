# 源码审查整改索引

更新：2026-11-04。用户已明确恢复原整改、测试和逐项推送合并；清理结果保留。

权威进度见根目录 `Mneme-全面源码审查与优化清单-2026-10-30.md`：27 个 P 条目已完成 19、未完成 8；另有发布收口 1，合计剩余 9。MN 编号是另一种拆分，不重复计数。

## 已合并批次

以下 PR 保存对应变更、验证及 CI 历史；删除本地历史日志不代表重新运行测试。

| PR | 内容 |
| --- | --- |
| [#44](https://github.com/CoderDongHuang/Mneme/pull/44) | SMTP 配置 |
| [#46](https://github.com/CoderDongHuang/Mneme/pull/46) | Redis 认证与 AOF |
| [#47](https://github.com/CoderDongHuang/Mneme/pull/47) | 记忆日志隐私 |
| [#48](https://github.com/CoderDongHuang/Mneme/pull/48) | FTS 失败传播 |
| [#49](https://github.com/CoderDongHuang/Mneme/pull/49) | 模型密钥轮换 |
| [#50](https://github.com/CoderDongHuang/Mneme/pull/50) | 上游流关闭 |
| [#51](https://github.com/CoderDongHuang/Mneme/pull/51) | 会话写入节流 |
| [#52](https://github.com/CoderDongHuang/Mneme/pull/52) | 原子配额 |
| [#53](https://github.com/CoderDongHuang/Mneme/pull/53) | 导航数据化 |
| [#54](https://github.com/CoderDongHuang/Mneme/pull/54) | 不可变镜像 |
| [#55](https://github.com/CoderDongHuang/Mneme/pull/55) | 流式指标 |
| [#56](https://github.com/CoderDongHuang/Mneme/pull/56) | 时区与格式 |
| [#57](https://github.com/CoderDongHuang/Mneme/pull/57) | 上传取消 |
| [#58](https://github.com/CoderDongHuang/Mneme/pull/58) | 删除任务租约 |
| [#59](https://github.com/CoderDongHuang/Mneme/pull/59) | 数据库最小权限 |
| [#60](https://github.com/CoderDongHuang/Mneme/pull/60) | 索引修复 |
| [#61](https://github.com/CoderDongHuang/Mneme/pull/61) | 文档与知识库删除核验 |
| [#62](https://github.com/CoderDongHuang/Mneme/pull/62) | 邮箱验证 |
| [#63](https://github.com/CoderDongHuang/Mneme/pull/63) | 样式与格式 |
| [#64](https://github.com/CoderDongHuang/Mneme/pull/64) | 索引 generation |
| [#65](https://github.com/CoderDongHuang/Mneme/pull/65) | 任务状态 |
| [#66](https://github.com/CoderDongHuang/Mneme/pull/66) | 回答原子持久化 |
| [#67](https://github.com/CoderDongHuang/Mneme/pull/67) | 停止与断连 |
| [#68](https://github.com/CoderDongHuang/Mneme/pull/68) | 资料并发隔离 |
| [#69](https://github.com/CoderDongHuang/Mneme/pull/69) | 资料页状态 |
| [#70](https://github.com/CoderDongHuang/Mneme/pull/70) | 引用契约 |
| [#71](https://github.com/CoderDongHuang/Mneme/pull/71) | 会话清理读回 |
| [#72](https://github.com/CoderDongHuang/Mneme/pull/72) | 记忆页状态 |
| [#73](https://github.com/CoderDongHuang/Mneme/pull/73) | 隐私页状态 |
| [#74](https://github.com/CoderDongHuang/Mneme/pull/74) | 复习页状态 |
| [#75](https://github.com/CoderDongHuang/Mneme/pull/75) | 候选 outbox |
| [#76](https://github.com/CoderDongHuang/Mneme/pull/76) | 测验页状态 |
| [#77](https://github.com/CoderDongHuang/Mneme/pull/77) | embedding 超时 |
| [#78](https://github.com/CoderDongHuang/Mneme/pull/78) | 输入快照 |
| [#79](https://github.com/CoderDongHuang/Mneme/pull/79) | 文档核对 |
| [#80](https://github.com/CoderDongHuang/Mneme/pull/80) | 运维页状态 |
| [#81](https://github.com/CoderDongHuang/Mneme/pull/81) | 设置页状态 |
| [#82](https://github.com/CoderDongHuang/Mneme/pull/82) | 反思 owner |
| [#83](https://github.com/CoderDongHuang/Mneme/pull/83) | 反思计数 |
| [#84](https://github.com/CoderDongHuang/Mneme/pull/84) | 反思账号清理 |
| [#85](https://github.com/CoderDongHuang/Mneme/pull/85) | 供应商日志隐私 |
| [#86](https://github.com/CoderDongHuang/Mneme/pull/86) | 反思结果校验 |
| [#87](https://github.com/CoderDongHuang/Mneme/pull/87) | 演练页状态 |
| [#88](https://github.com/CoderDongHuang/Mneme/pull/88) | 整站恢复状态 |
| [#89](https://github.com/CoderDongHuang/Mneme/pull/89) | 个人恢复请求作用域 |
| [#90](https://github.com/CoderDongHuang/Mneme/pull/90) | Trace 围栏 |
| [#91](https://github.com/CoderDongHuang/Mneme/pull/91) | manifest 围栏 |
| [#92](https://github.com/CoderDongHuang/Mneme/pull/92) | 长期记忆围栏 |
| [#93](https://github.com/CoderDongHuang/Mneme/pull/93) | 缓存围栏 |
| [#94](https://github.com/CoderDongHuang/Mneme/pull/94) | Redis 日志隐私 |
| [#95](https://github.com/CoderDongHuang/Mneme/pull/95) | 会话记忆账号围栏 |
| [#96](https://github.com/CoderDongHuang/Mneme/pull/96) | 单会话删除 |
| [#97](https://github.com/CoderDongHuang/Mneme/pull/97) | 持久反思回执 |
| [#98](https://github.com/CoderDongHuang/Mneme/pull/98) | 基础设施业务诊断 |
| [#99](https://github.com/CoderDongHuang/Mneme/pull/99) | 三端共享 SSE 契约；恢复后桌面和手机真实回归均通过 |
| [#100](https://github.com/CoderDongHuang/Mneme/pull/100) | 文档精简、历史材料清理与权威进度整理；9 项 CI 全通过 |
| [#101](https://github.com/CoderDongHuang/Mneme/pull/101) | 长期记忆读取失败安全处理；9 项 CI 全通过 |
| [#102](https://github.com/CoderDongHuang/Mneme/pull/102) | 分析页窗口、读取与反馈状态；9 项 CI 全通过 |
| [#103](https://github.com/CoderDongHuang/Mneme/pull/103) | 账号当前/历史文件与缓存核验、运行挂载门禁；9 项 CI 全通过 |

## 当前未完成工作

- 账号当前/历史文件与缓存核验已合并 #103；18 项最终汇总核验已通过本地三端测试及桌面/手机真实回归，待本批 CI 和合并。SQLite WAL/文件空间策略及留存维护仍待完成。协议见 [删除核验](DELETION_VERIFICATION.md)。
- SSE 已合并；其他 REST 契约仍待验收，不能关闭完整 P3-06。
- P1-05、P1-06、P2-12、P2-14、P3-03、P3-04、P3-05、P3-06 及发布收口仍待完成。

## 本地材料保留原则

不再逐问题复制全量数据目录。`本地历史产物已清理；证据见整改索引中的 PR` 只保留恢复工作的必要补丁、源码哈希和简短交接；尚未验收的工作保留必要夹具。仅保留最近一组匹配回退资料，历史批次从 Git/PR 追溯。
每项以原文、代码、测试、真实部署及合并结果联合验收，再更新原文勾选与剩余数量。

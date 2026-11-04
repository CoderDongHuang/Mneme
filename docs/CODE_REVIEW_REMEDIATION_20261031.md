# 源码审查整改索引

更新：2026-11-04。用户已明确恢复原整改、测试和逐项推送合并；清理结果保留。

权威进度见根目录 `Mneme-全面源码审查与优化清单-2026-10-30.md`：27 个 P 条目已完成 20、未完成 7；另有发布收口 1，合计剩余 8。MN 编号是另一种拆分，不重复计数。

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
| [#104](https://github.com/CoderDongHuang/Mneme/pull/104) | 账号 18 项最终核验、限流预算隔离与记忆提交回执；9 项 CI 全通过 |

| [#105](https://github.com/CoderDongHuang/Mneme/pull/105) | SQLite 五库停写维护与限流测试有界清理；当前 HEAD 的 9 项 CI 全通过，P1-05 关闭 |

| [#106](https://github.com/CoderDongHuang/Mneme/pull/106) | 蒸馏结果严格校验；当前 HEAD 的 9 项 CI 全通过，不关闭完整 P1-06 |
| [#107](https://github.com/CoderDongHuang/Mneme/pull/107) | 诊断锁在发送响应前释放及停止测试清理；当前 HEAD 的 9 项 CI 全通过 |
| [#108](https://github.com/CoderDongHuang/Mneme/pull/108) | 文档解析模块边界；当前 HEAD 的 9 项 CI 全通过，不关闭完整 P2-14 |
| [#109](https://github.com/CoderDongHuang/Mneme/pull/109) | 任务中心读取与提交回执边界；当前 HEAD 的 9 项 CI 全通过，不关闭完整 P3-03/P2-14 |

| [#110](https://github.com/CoderDongHuang/Mneme/pull/110) | 普通 Result 共享契约与 null 回执；当前 HEAD 的 9 项 CI 全通过并合并 |
| [#111](https://github.com/CoderDongHuang/Mneme/pull/111) | 知识库独立读取、慢刷新筛选及预览归属保护；最终 HEAD bb58858 的 9 项 CI 全通过并合并 |

## 当前未完成工作

- 学习记忆独立读取与回执保护子项本地完成，待独立 PR 当前 HEAD 的 9 项 CI：前端全量 434 项、Lint/构建、常规浏览器 60 项及最终镜像 localhost 桌面/手机 2 项真实回归通过（31.7 秒）。非法数据安全失败、旧请求失效、真实保存/恢复/删除、手机菜单遮挡及账号归零已核对；完整 P3-03/P2-14 未关闭，剩余 8。

- 知识库读取与异常状态子项本地完成，待当前 HEAD 全部 9 项 CI：前端全量 405 项、Lint/构建、浏览器 60 项及最终镜像 localhost 桌面/手机 2 项通过（33.5 秒）；真实上传解析、独立重试、删除后断网、一次 DELETE、SQL 归零和两端截图核对通过。解析报告异常嵌套字段安全失败；无新 CSS/依赖/迁移。完整 P3-03/P2-14 不关闭，剩余 8。

- 任务中心读取/提交回执边界已合并 #109：定向 23 项、前端 337 项、ESLint/构建及 localhost 桌面/手机 2 项通过；worker 完成、QA 账号与任务清零、两端截图核对通过。不关闭完整 P3-03/P2-14，剩余 8。

- P2-14 文档解析边界已合并 #108：独立解析模块保留 11 个函数/类行为及兼容导出；Linux 全量 1097 项和新增独立进程测试 1 项通过，Windows 定向 25 项加边界 1 项通过（缺 Tesseract 的 OCR 1 项跳过）；localhost 桌面/手机真实多格式、OCR、页图与引用共 4 项通过。Ruff、ESLint、YAML 校验通过；不关闭完整 P2-14，剩余 8。

- 基础设施诊断锁回归缺陷已合并 #107：发送成功或异常响应前释放操作锁，真实 HTTP 线程阻塞回归、Windows 16 项、Linux 全量 1080 项与 localhost 桌面/手机运维诊断 2 项通过。主项剩余 8。

- P1-06 蒸馏结果校验已通过 Windows 定向 71 项、Linux Python 全量 1077 项和 localhost 桌面/手机 2 项真实回归，#106 当前 HEAD 的 9 项 CI 全通过并合并；完整回答后记忆任务仍未解耦，不关闭主项。
- 账号汇总 CI 暴露的共享限流饥饿与写入误报已修复：推理/交互/清理核验使用三个固定预算，配置限额保持不变；记忆保存、恢复、删除直接返回提交回执，移除提交后的列表依赖。Linux Python 全量 1066 项、Windows 定向 25 项、Java 全量 250 项无失败/跳过、前端 322 项及 localhost 桌面/手机真实记忆变更和限流聊天 4 项通过。相同 Gateway 网络来源真实耗尽维护预算后交互读取仍为 200；CI 已启用真实限流聊天回归。Ruff、ESLint、构建和 diff 通过，账号报告 #104 的 9 项 CI 已全通过并合并。
- 账号当前/历史文件与缓存核验已合并 #103；18 项最终汇总核验 #104 已通过 9 项 CI 并合并。SQLite 停写维护 #105 已在当前 HEAD 的 9 项 CI 全通过后合并，并修复真实限流测试设置/清理的有界 Retry-After 等待（localhost 桌面/手机 2 项通过）；P1-05 关闭；当前在线文件回收和备份/介质留存保证分别定义。协议见 [删除核验](DELETION_VERIFICATION.md)。
- 普通 Result 外壳契约已合并 #110，当前 HEAD 的全部 9 项 CI 均通过：共享 23 个正反例、Java 实际序列化与浏览器、生成 TypeScript 漂移门禁；拒绝损坏成功回执，保留 null/falsy 和固定健康裸对象协议。Java 全量 254 项及最终定向 11 项、Python 契约 61 项、前端全量 375 项、Ruff/ESLint/构建通过；最终镜像 localhost 桌面/手机 2 项真实回归（15.2 秒）、截图、账号 SQL 清零和部署参数核对通过。其他业务 data/请求/状态枚举契约仍待验收，不能关闭完整 P3-06，剩余 8。见 [普通响应契约](api.md#result-json-contract)。
- P1-06、P2-12、P2-14、P3-03、P3-04、P3-05、P3-06 及发布收口仍待完成，共 8 项。

2026-11-05 知识库 PR #111 的真实桌面 CI 失败已复现：筛选隐藏默认文档时旧预览访问空对象，另补修慢刷新隐藏筛选提示。预览按 ID/版本/重试归属隔离，新增慢请求及组件回归；最终前端 408 项、Lint/构建、localhost 桌面/手机 2 项（39.6 秒）及四张截图核对通过。待新 HEAD 全部 9 项 CI；完整主项剩余 8。

## 本地材料保留原则

不再逐问题复制全量数据目录。`本地历史产物已清理；证据见整改索引中的 PR` 只保留恢复工作的必要补丁、源码哈希和简短交接；尚未验收的工作保留必要夹具。仅保留最近一组匹配回退资料，历史批次从 Git/PR 追溯。
每项以原文、代码、测试、真实部署及合并结果联合验收，再更新原文勾选与剩余数量。

2026-11-05 合入知识库预览回归补修后，学习记忆与知识库组合验收：前端全量 437 项、ESLint、构建与体积门禁通过；最终组合镜像 localhost 桌面/手机 4 项真实回归通过（57.4 秒），14 张截图已核对。独立 PR 仍须当前 HEAD 的全部 9 项 CI 通过后合并，主项剩余 8。

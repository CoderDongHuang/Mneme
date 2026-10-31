# 文档索引解析代与旧 worker 隔离

适用：V30 及其配套 Gateway、Python Agent。此机制补充任务 owner lease，不提供 Qdrant、FTS 与 MySQL 之间的 ACID 事务。

## 写入与发布

Gateway 在持久任务的 owner/fence 事务内锁定文档行，以条件 SQL 增加 `knowledge_document.index_generation`。普通实体更新不能写这个字段。请求和报告必须带相同文档 ID、任务 ID 与解析代；过时、删除中、已换任务的结果不能发布。旧版 Gateway 向新 Agent 发送缺少解析代的持久任务会收到 422，应配套升级。

Python 将 `document_id`、`index_generation` 同时写入 chunk metadata，chunk ID 也包含解析代。持久 manifest 记录每文档的 `latest`（已预留）和 `active`（已发布）。开始解析时先登记严格递增的 latest；解析、OCR、Embedding 均在锁外。实际 Qdrant upsert、FTS replace 与 active 发布受同一数据库事务的写锁保护，进入锁后再次验证 latest。旧 worker 即使刚通过 Redis 租约检查后被暂停，恢复后也不能进入新代的存储变更。该锁不会因 Redis TTL 到期而转交，持有进程退出时数据库回滚并释放。

active 提交后，另一次持锁校验清理旧 chunk。新 worker 或删除已接管时，旧 worker 不做清理。暂停发生在持锁变更内部时，其他写入等待该事务结束，不能越过同一把锁发布新代。

## 查询与故障恢复

- Qdrant 的精确、ANN 与 BM25 降级均在排名/limit 前筛选 active；FTS 命中按 active Qdrant 的正文和 metadata 重新核验。检索返回前再次核验 active。文档 chunk 预览与用户统计采用相同过滤。
- FTS 出错时保留现有 `index_pending`、dense 可用和持久修复任务。reconciliation 在同一 generation 写锁中核验向量版本并重建 FTS，不重新生成向量。已经开始更新解析代的文档应先重试解析，再修复对应版本。
- upsert 成功而 manifest 尚未提交时进程失败，新 chunk 属于未发布数据，查询不可见；旧 active 仍可读取。重试解析分配更高代并清理此前残留。FTS 可能暂时对应未发布代，查询经 canonical 核验后使用 Qdrant BM25 降级。不能据此声称跨库原子提交。
- 删除先持久提交文档/知识库/用户 tombstone，再在相同用户锁内物理删除并严格读回。故障可重试；已经删除的范围拒绝在途与晚到写入。tombstone 只保留范围 ID 和版本标记，用于阻止复活，不保存正文；此处不替代账号其他存储的最终删除核验。
- 取消解析使用独立内部清理接口，持久记录暂停与已取消代的上限，并隐藏全部旧 chunk；不永久删除文档 ID。清理失败仍隐藏并可重试，旧 worker 不能继续发布。用户显式重试分配更高代，只有成功发布才解除暂停；永久删除标记始终不能由取消或重试清除。
- manifest 丢失时，有 generation 的向量不会被猜测为当前版本；manifest 读失败时操作失败，不退回未过滤结果。应恢复匹配备份，或在停写核实后对受影响文档重新解析。不要手工清空 manifest 作为常规修复。
- 升级前无 generation 的 chunk 可按旧格式读取；文档第一次发布新代后会淘汰旧 chunk。历史索引的版本建立仍遵循索引一致性说明。

## 单机与多实例

单机默认 `INDEX_GENERATION_PATH=data/index-generations.sqlite3`，使用 SQLite `BEGIN IMMEDIATE`；这实际上串行所有用户的短索引变更。多实例必须使用 `AUXILIARY_STORE_BACKEND=mysql`，V30 的 `knowledge_index_state` 按用户行 `SELECT FOR UPDATE`，不同用户可并行。表由 Flyway 维护，Agent DML 账号不执行 DDL。

单用户的索引变更仍串行。查询过滤条件随该知识库 manifest 文档数线性增长；大规模导入应评估数据库锁等待、Qdrant 查询和 metadata 过滤大小。这里没有以小数据并发测试代替容量基准。

## 配套升级、备份和回滚

1. 停止所有旧 Gateway/Agent 写入者及维护写入进程，保存一致的 MySQL、Qdrant、FTS 与 Agent data 备份；保留当前镜像与配置。
2. 先由独立 Flyway 账号执行 V30，再运行配套的新 Agent/Gateway。不能让旧 Agent 绕过 generation 锁继续写同一索引。
3. 默认整站备份包含完整 `python-agent/data`，因而包含 SQLite manifest；共享 MySQL manifest 包含在业务 schema 的 SQL dump 中。若自定义 `INDEX_GENERATION_PATH` 位于此目录之外，必须额外纳入同一停写快照，并恢复到同一路径。仅保存向量和 FTS 不足以恢复已发布代。
4. 验证现有文档可读，新上传/替换及删除成功；执行 `python scripts/check_index_generation.py` 时需 `AUXILIARY_STORE_BACKEND=mysql`。该脚本仅创建并清理唯一探针行，验证跨连接、进程退出释放锁和 tombstone。
5. 回滚时停下新写入者，恢复整套匹配数据与旧镜像，包括 Flyway 历史；不能仅回退二进制或仅删 V30 字段。保留失败状态用于诊断，恢复失败应维持停写。

## 回归覆盖

`tests/test_index_generations.py` 覆盖 lease 检查后暂停、精确/ANN/降级检索、删除复活、写后失败、重启及 manifest 丢失；Java `IndexGenerationConcurrencyTest` 使用真实 MySQL 验证迁移、并发分配、条件更新与回滚。

真实整栈 `frontend/e2e/index-generation-real.spec.js` 用新建隔离账号保留一个独立旧入库进程的有效 Redis lease，在进入写锁前暂停；经真实 Gateway 替换文件。第一次请求遇到已预留代时拒绝，持久重试分配更高代。新版就绪后恢复旧进程，验证其被 generation 拒绝，Qdrant 全部内容和向量摘要、FTS 版本不变，真实检索和网页预览仍为新版。该用例分别运行桌面与移动端，不对业务 HTTP 响应做 mock。

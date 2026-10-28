# Embedding 索引迁移

此版本为知识库和长期记忆保存 `embedding_profile`。相同维度不代表相同向量空间。
更换供应商/模型、离线与云端切换，或者旧集合没有 profile 时，语义读写会明确拒绝；
列表、导出、删除仍可使用。供应商暂时故障会保留原索引并报错，不再写入离线替代向量。

## 升级顺序

1. 按 [自托管指南](SELF_HOSTING.md) 的备份恢复流程备份关系库、文件、向量库及辅助状态，并验证备份。
2. 停止网关、Agent 和所有后台 worker，保留 Qdrant 服务。迁移期间不得写入。
3. 配置目标模型和原来的 `VECTOR_STORE_MODE/QDRANT_URL/QDRANT_PATH`。离线选择必须明确设置
   `MNEME_OFFLINE_EMBEDDINGS=true`；云端需有效 `DASHSCOPE_API_KEY`。
4. 使用 Agent 的 Python 3.11 环境运行（Docker 中可用同一 Agent 镜像执行一次性命令）：

   ```bash
   python python-agent/scripts/rebuild_embeddings.py --collection user_1_kb_1
   python python-agent/scripts/rebuild_embeddings.py --collection user_1_kb_1 --apply --services-stopped --backup /protected-backup/kb1-before.json
   ```

   默认仅显示集合、数量和配置，不修改数据。每个集合单独执行，长期记忆集合为
   `mneme_long_term_memory`。分片部署先指定单个分片地址并设置 `VECTOR_SHARD_COUNT=1`。
   需至少容纳快照三倍大小的空闲空间；快照含私人正文和旧向量，勿提交到 Git。
5. 脚本创建独占快照和 SHA-256 校验，先完整生成新向量再修改原集合；保留 ID、正文、
   归属及来源，写入异常时尝试恢复旧向量。进程被强制结束仍需人工恢复，不能当成数据库事务。
6. 重启服务，核对集合数量、两用户隔离、检索和引用，再保存完整系统备份。

旧数据没有正文时，应从原始文件新建知识库并重传；不会猜测或直接给旧向量补一个 profile。
旧版使用特殊字符或超长租户/知识库 ID 的集合名有碰撞风险，此版本使用摘要名称；这种集合应
从原文件迁入新的知识库，不自动合并，也不自动删除旧集合。

## 回滚

停止写入，恢复原环境配置，执行：

```bash
python python-agent/scripts/rebuild_embeddings.py --collection user_1_kb_1 --apply --services-stopped --restore /protected-backup/kb1-before.json
```

恢复会检查快照校验和、schema、集合名和全部 ID；若集合成员已改变则拒绝，需使用完整备份恢复。
回退应用版本时，数据库新增的 `parse_report` 列可保留；勿手工删除 Flyway 历史记录。

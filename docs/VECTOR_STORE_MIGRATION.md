# Chroma → Qdrant 迁移

2026-10-29 起，运行时使用 Qdrant 服务与 Python 客户端 1.20.0，不再安装 Chroma。迁移保持原集合名、点 ID、正文、元数据、Embedding profile 和向量；不会重新调用模型。Java 的 `chroma_collection_id` 是历史数据库列名，本次保留以避免破坏 Flyway 历史校验，不代表仍使用旧库。

## 新安装

直接按 README 启动。容器使用 `VECTOR_STORE_MODE=http`、`QDRANT_URL=http://qdrant:6333`；原生开发默认 `VECTOR_STORE_MODE=local`，数据位于 `QDRANT_PATH`。本地模式共享同进程客户端，不支持多个进程同时打开相同目录。Qdrant 不发布宿主机端口，仅 Agent 可访问内部网络。外部服务须单独配置受控地址、TLS 和 `QDRANT_API_KEY`。

## 现有单节点部署

1. 记录旧 Git 提交、配置和镜像，先按旧版本工具制作并验证整栈备份；安全保存加密/签名密钥。备份与导出包含私人正文和向量，不得提交 Git 或上传公开日志。
2. 停止网关、Agent 和全部后台写入者，保持旧 Chroma 运行。不要删除旧容器或卷，不要使用 `--remove-orphans`。导出期间不得修改源库。
3. 保留旧镜像后构建新 Agent。导出工具仅使用 HTTP 标准库，可在能访问旧库的隔离网络中执行。默认源为 `http://chroma:8000`，仅导出 Chroma v2 API 的 `default_tenant/default_database`；自定义租户/数据库必须逐一适配导出，不能当作已覆盖。

```sh
docker compose build python-agent
docker compose run --rm --no-deps --entrypoint python python-agent scripts/migrate_vector_store.py export --snapshot /data/legacy-vector.json --source-url http://chroma:8000 --services-stopped
```

快照及同名 `.sha256` 必须使用新文件名；目标父目录需已存在。原生旧本地库需先在隔离环境用旧版本服务打开数据副本，再通过 HTTP 导出，不要往新运行时重新安装有漏洞的 Chroma。

4. 启动空 Qdrant，先检查快照，再显式执行迁入：

```sh
docker compose up -d qdrant
docker compose run --rm --no-deps --entrypoint python python-agent scripts/migrate_vector_store.py import --snapshot /data/legacy-vector.json --target-url http://qdrant:6333 --services-stopped
docker compose run --rm --no-deps --entrypoint python python-agent scripts/migrate_vector_store.py import --snapshot /data/legacy-vector.json --target-url http://qdrant:6333 --services-stopped --apply
```

第一条 import 只检查快照，不验证目标连通性。实际迁入要求目标完全为空（包括迁移回执）；拒绝覆盖。默认维度 1024；其他维度通过 `--dimension` 指定；当前应用固定 1024，其他维度需同步适配应用。脚本检查 SHA-256、重复 ID、有限向量、集合计数、正文、元数据及每条向量，成功后写隐藏迁移回执。失败会清理本次新建集合，源库与快照不变；网络中断等原因若令清理也失败，应保留日志并选择新的空目标重试，不能删源库。

Qdrant 的 cosine 距离会归一化向量；非归一化 cosine 历史数据可能无法通过严格向量核对，应在副本上确认归一化语义并提供独立迁移验证，不能跳过校验。Mneme 默认 L2，适配层将欧氏距离平方后维持旧检索阈值语义。

5. 启动应用并验证旧账号资料、检索、引用、长期记忆、新上传和删除，再执行真实浏览器回归：

```sh
docker compose up -d python-agent java-gateway
cd frontend
MNEME_REAL_E2E=true MNEME_E2E_BASE_URL=http://localhost:3000 npx playwright test e2e/real-stack.spec.js e2e/roadmap-stack.spec.js --retries=0
```

确认通过后停止旧 Chroma 容器，继续保留旧数据和受保护备份。新栈检测到 `CHROMA_PATH`、本地旧目录或 `/data/chroma` 下旧 SQLite 时，若对应目标无迁移回执会拒绝启动，禁止靠删旧目录绕过。

## Demo、多节点与备份

Demo 使用同一 Compose 项目及原 `.env`；先停止写入，保留并只读挂载旧 `demo-chroma` 卷。导出/迁入命令需改为实际 demo Compose 文件及快照挂载路径。分片部署必须保持节点顺序、分片数和路由不变，逐节点导出和迁入；两个 Agent 均只读挂载旧分片卷以触发保护，每个目标节点都需自己的回执。长期记忆在主节点。应用分片不是 Qdrant 原生副本集，不能宣称单节点中断时零故障。

统一备份新增 `data/qdrant`，仍允许旧 `data/chroma` 以验证、恢复历史归档。恢复仅含旧库的备份后必须先迁移，不能直接启动新应用。备份工具不会备份外部托管 Qdrant，需独立快照；Demo/分片命名卷也须独立备份，不要把主栈目录备份当作其备份。

回滚须停止新写入、恢复与旧镜像匹配的整栈备份，并在隔离网络运行。迁移后新增数据不会自动同步回旧库；旧镜像仍含已知 Chroma 漏洞，只能用于受控恢复，不是长期修复。

## 上游依据

- [Qdrant 1.20.0 官方发布](https://github.com/qdrant/qdrant/releases/tag/v1.20.0)
- [Chroma 未合并修复提案 #7602](https://github.com/chroma-core/chroma/pull/7602)：不能视为官方已修复版本。
- [安全策略](SECURITY_RESPONSE_POLICY.md)与[本轮验收](ACCEPTANCE_2026-10-29.md)。

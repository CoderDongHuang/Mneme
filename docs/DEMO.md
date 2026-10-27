# 无外部模型的隔离演示

此模式只使用合成资料和本地确定性向量，返回明确标注的原文摘录。它用于验证账号、上传、解析、检索、引用和诊断流程，不代表模型的推理、测验或语义质量。首次安装依赖网络下载镜像和包，运行演示不需要外部模型账号。

## 一条完整路径

前置：Git、Python 3.10+（无需安装 Agent 依赖）、Docker Engine / Docker Desktop、Compose v2。推荐 4 核、8 GB 内存、20 GB 可用磁盘；首次构建通常需要数分钟，取决于网络。

```bash
git clone https://github.com/CoderDongHuang/Mneme.git
cd Mneme
docker version
docker compose version
python scripts/demo.py start
python scripts/demo.py status
```

1. 打开 <http://localhost:3000/auth>，确认顶部“离线演示”提示，注册本地账号。无预置管理员、无公开默认密码。
2. 新建资料库，上传 `test-fixtures/rag-fixture.txt`。它是固定的虚构资料，不含真实个人数据。
3. 等待可检索状态并查看解析报告，提出“星桥计划的核心识别码是什么？请引用资料”。应能打开含 `QZ-7294` 的原文依据。
4. 打开设置 → 检测连通性。Chat 与 Embedding 为本地；Rerank 禁用；OCR 检查本地语言包。检测全部为绿色也不能代替业务链路验收。
5. 密码重置邮件在 <http://localhost:8025> 查看；Mailpit 不向真实邮箱发信。

## 测试、停止和清理

CI 每次从干净检出和独立空卷开始，真实构建所有服务后运行 `frontend/e2e/demo-stack.spec.js`，验证上传、解析、引用问答、诊断及匿名接口拒绝访问。日志、截图和失败 trace 为 Actions 的 `offline-demo-acceptance` 产物。手动执行（另需 Node 22）：

```bash
cd frontend
npm ci
npx playwright install chromium
```

PowerShell 设置 `$env:MNEME_DEMO_E2E='true'`、`$env:MNEME_E2E_BASE_URL='http://127.0.0.1:3000'`，Bash 使用同名 `export`，再运行 `npx playwright test e2e/demo-stack.spec.js --project=桌面端`。

```bash
# 从仓库根目录执行
python scripts/demo.py logs
python scripts/demo.py stop
python scripts/demo.py start
# 不可逆地删除且只删除演示栈卷，需明确参数
python scripts/demo.py clean --confirm-delete-demo-data
```

`stop` 保留演示卷；`clean` 删除 `mneme-demo` 演示卷，不作用于正式栈。`.env.demo.local` 为独占创建的随机本地密钥文件，Git 已忽略；不要提交、共享或在日志中打印。文件在 Windows 上继承目录 ACL；部署者应限制工作目录访问。

## 常见错误

| 现象 | 排查与操作 |
|---|---|
| 无法连接 Docker / 命令长时间无响应 | 打开 Docker Desktop，确认 `docker version` 有 Server 输出；先修复引擎，不要删除其他项目容器 |
| 3000 / 8025 被占用 | 启动前 PowerShell 设置 `$env:DEMO_PORT='3001'`、`$env:DEMO_MAIL_PORT='8026'`；Bash 使用同名 export；修改后访问新端口 |
| 拉取镜像、npm 或 pip 超时 | 检查代理、DNS、镜像注册表连通性；修复后重跑 start，保留缓存，不要跳过哈希验证 |
| MySQL 未就绪 | status/logs 查看 mysql；检查磁盘和内存；不要对正式数据执行清理 |
| 页面可打开但注册请求失败 | 检查 java-gateway/mysql 日志和 `/api/v1/health`；UI 存活不等于数据库可用 |
| 文件失败或部分解析 | 打开解析报告，核对文件、OCR/表格警告及页码，修正环境后重试；损坏文件应明确失败 |
| 无模型密钥 | 演示无需密钥；真实模式必须配置服务端供应商。不要把原文摘录当作云模型回答 |
| 模型切换后索引不兼容 | 不要给旧集合手动改 profile，按 [Embedding 迁移](EMBEDDING_MIGRATION.md) 备份、dry-run、重建 |

正式部署的备份脚本面向正式栈的数据布局，不直接用于这套独立命名卷；演示数据应保持可丢弃。需要保留真实资料请使用正式栈及已验证的备份流程。

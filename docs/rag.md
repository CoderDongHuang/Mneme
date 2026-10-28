# 文档解析与 RAG

## 处理链路

1. Java 校验用户对知识库的所有权并保存原文件。
2. Java 创建文档元数据和 MySQL 持久化处理任务；后台任务服务认领任务并调用 Python 的同步入库接口。
3. Python 解析并建立索引，Java 根据调用结果推进任务状态；失败任务保留重试信息。
4. 解析器按格式还原页码、章节、表格和正文。
5. 切片器保持结构化元素完整，对正文执行带重叠的语义段落切分。
6. Qdrant 按用户和知识库隔离存储；SQLite FTS5 同步维护持久化词法索引。
7. 检索使用 Dense、FTS5 词法召回和 RRF；可通过配置懒加载 Cross Encoder。
8. 前端轮询 Java 文档状态，读取 `ready / partial / failed`、chunk 数量与 `parseReport`。部分成功保留逐页警告，不冒充完整解析。

## 支持格式

| 格式 | 处理方式 |
|---|---|
| PDF | PyMuPDF 版面块排序、重复页眉页脚过滤、pdfplumber 表格、逐页 Tesseract 中文/英文 OCR、可选 Qwen-VL |
| DOCX | 标题、段落、表格 |
| PPTX | 幻灯片标题、文本框、表格、可选内嵌图片理解 |
| XLSX/XLSM | 工作表结构化文本、可选内嵌图片理解 |
| CSV | 行列结构化文本 |
| MD/TXT/HTML | 段落与章节文本 |

## 检索与引用

默认返回相似度最高的 6 个片段。Prompt 中为片段编号，API 同时返回完整 `sources`。前端引用抽屉显示文档、页码、章节和原文。

词法索引配置：

- `LEXICAL_INDEX_PATH`：SQLite 文件路径，默认 `python-agent/data/lexical-index.sqlite3`。
- `RERANKER_ENABLED=true`、`RERANKER_PROVIDER=dashscope` 与 `RERANKER_MODEL=gte-rerank-v2`：使用现有 DashScope SDK 在线重排；也可将 provider 设为 `cross_encoder` 使用本地模型。失败时自动降级到 RRF。默认关闭。`RERANKER_MIN_SCORE` 默认 0，仅过滤 DashScope 的归一化 0–1 分数；不应用于 CrossEncoder logits。成功的空结果保持为空。0.25 阈值在完整 110 题云实验中导致召回下降，不能直接照搬小样本阈值。
- `VECTOR_SHARD_URLS=http://qdrant-1:6333,http://qdrant-2:6333`：按 `user_id + kb_id` 稳定哈希到独立 Qdrant 节点；`VECTOR_SHARD_COUNT` 应与地址数量一致。

## 生产评测建议

- 检索命中率、MRR、Recall@K。
- 页码和章节引用正确率。
- 表格行列保持率。
- OCR 字符错误率。
- 无依据回答比例与引用覆盖率。

## 内置基线评测

`python-agent/evaluation/rag_cases.json` 当前包含 110 条稳定的虚构问题，覆盖 PDF、CSV/XLSX、PPTX、Markdown、HTML、OCR 策略、跨主题检索和无答案问题。每条记录支持 `expected_sources`、`expected_terms`、`answerable`、`category` 和可选 `expected_page`。`python-agent/scripts/evaluate_rag.py` 输出：

- `Hit@K`：Top-K 中是否命中正确来源和关键事实。
- `Recall@K`：可回答问题的证据召回率。
- `MRR`：正确片段的平均倒数排名。
- `top_evidence_term_support`：Top-K 首片段包含标注关键事实的离线证据 proxy，不等价于 RAGAS/LLM Faithfulness。
- `top_evidence_precision / evidence_hit_recall`：首片段相关性和问题级证据覆盖率；没有生成答案，不能称为答案引用准确率。
- `no_answer_evidence_absence`：schema 4 使用 `not chunks`，只有确实没有召回片段才通过无答案题；scoring version 为 2。schema 3 的 `not relevant_ranks` 在空来源标注时恒真，历史分数不能与新分数直接比较。空召回不等于生成层正确拒答，后者仍须查看 `answer_abstention_accuracy` 和人工复核。
- `citation_metadata_completeness`：引用是否完整包含文档、页码、章节和内容类型。
- `p95_latency_ms`：检索 P95 延迟。
- `estimated_input_tokens / estimated_input_cost`：按字符近似 token 的输入成本估算；使用 `--input-cost-per-million` 指定价格。

离线运行示例：

```powershell
$env:MNEME_OFFLINE_EMBEDDINGS="true"
$env:RETRIEVER_REWRITE_ENABLED="false"
$env:RERANKER_ENABLED="false"
python python-agent/scripts/evaluate_rag.py --input-cost-per-million 0.15
```

当前评测结果应作为回归基线，而不是生产质量承诺；真实扫描 PDF、复杂表格、公式和跨页问题仍需人工标注与视觉评测。


## 2026-10 证据完整性修复

提示词、同步响应和 SSE 来源列表统一按实际进入上下文的片段编号，允许跨文档引用。上下文长度截断后的内容也同步反映在来源中。资料中的角色指令和命令作为不可信数据处理。

资料问答在展示前检查是否存在证据、引用是否缺失或越界；空资料直接拒答且不调用模型。随后将回答拆分为声明单元，要求核验模型逐项判断全部声明是否成立，并返回对应来源的逐字引文；程序验证引文确实属于指定片段。缺漏、异常、超时或不支持会拒绝展示。SSE 先缓存正文再核验，增加首段延迟和一次模型调用；闲聊继续逐段输出。相同模型的生成/核验存在相关性错误，逐字引文存在不代表严格蕴含证明；重要结论仍需原文复核。离线演示只摘录原文，确定性 CI 模型不验证语义。

词法索引属于派生数据，候选必须在当前租户的 Qdrant 集合内重新读取原文和元数据。删除中断留下的旧词法条目不会成为来源；Qdrant 不可用时不能绕过校验展示缓存内容。RRF 候选记录各通道排名；`RETRIEVER_REWRITE_ENABLED=false` 可独立关闭确定性查询改写。

报告现为 schema 4（无答案评分 version 2），记录数据集 SHA-256、Prompt/核验摘要、模型 profile、唯一运行集合与稳定用例 ID。原 `citation_precision` 等候选指标已更名；schema/数据集变化拒绝直接比较。真实模型样本使用生产 Prompt、相同上下文与核验器，保留生成/最终答案、评审理由及实际拒答指标；8 题抽样包含 2 道无答案题。流程改变后必须重新 bootstrap 可比模型历史，不能拼接旧分数声称提升。合成集不代表真实用户准确率。

## 联合范围、历史版本与解析预览

聊天与检索调试都先由网关按用户、活动知识库、ready/partial 文档解析允许列表，再进入向量和词法检索。指定文档、标签 AND、导入日期共同生效；词法 SQL 在 LIMIT 前应用文档筛选，并按当前向量原文重读候选。空允许列表严格不检索，不回退全库。日期针对数据库导入时间，不解释正文中的业务日期。

来源携带 SHA-256，打开原文时按 hash 选择对应文件、报告和页图；旧版本报告缺失会说明，未知 hash 拒绝。parser v3 提供有界逐页文字/文字层、OCR 区域置信度、正文/表格块和 chunk 摘要；达到预算标记截断。重复内容仅在原生文字页顶部/底部区域推断页眉页脚，不删除扫描页重复正文。

运行中入库支持协作取消：检查解析、OCR/模型调用前后与索引阶段，Python 退出后清理再落库；重试用新 job ID。活动锁为 UUID owner 的 60 秒 Redis 租约，每 20 秒续租；续租与释放使用 owner 比较 Lua，每个处理检查点也校验 owner。先生成 embedding，确认租约后再写向量。续租失败停止后续处理，进程强杀后最多一个 TTL 释放。外部调用仍须返回或超时；该机制不是 fencing，暂停恰好发生在检查与写入之间的竞态、跨存储整体原子性仍不保证。不要强删仍在运行的任务锁。

真实模型裁判对 expected_answer_points 逐项语义评分，保留 index/matched/reason 与 coverage（scoring version 1）。要点缺失、重复索引或无理由拒绝通过。比较报告额外检查模型配置、QA/核验摘要与评分版本；瞬时熔断计数不参与版本一致性判断。小样本裁判仍非人工质量保证。

2026-10-28 最终离线 110 题 P95=13.88ms、Recall@K=1.0、MRR=0.9556，四组共 140 题均通过原门禁，见 [回归记录](ACCEPTANCE_2026-10-28.md)。报告记录 retrieval 开关、provider/model/min_score；比较脚本拒绝配置不一致。云 embedding/重排报告不得与离线 embedding 基线直接比较；失败实验一并保留。

2026-10-29 更换 Qdrant 后，四组 140 题再次通过原门禁；110 题 P95=5.47ms、Recall@K=1.0、MRR=0.9556。结果仅为本轮环境测量，不将不同运行条件下的耗时差异宣称为数据库普遍性能提升。原始 JSON 见 [release-evidence-2026-10-29](../python-agent/evaluation/release-evidence-2026-10-29/)，当前验收见 [回归记录](ACCEPTANCE_2026-10-29.md)。


## 2026-10-28 无答案与云端延迟

`RETRIEVER_FOCUS_GATE_ENABLED=true` 默认启用保守的中文具体名词过滤，使用 jieba 词性，仅处理含“的/是否/有没有”的问句，排除抽象词。正文必须支持提取到的具体名词；文件名、章节标题不能代替正文证据。含少量价格/作者/地点等字段同义表达，可设为 false 独立对比。它是有限的词法启发式，可能误拒答，不覆盖所有中文同义、复杂指代或英文无答案场景。新增 holdout 为单一合成短文的 14 题，不能当作广泛真实资料准确率。

多条查询改写使用一次批量 embedding 和一次批量向量查询，保留各查询的通道排名。原离线 `rag_thresholds.json` 的 P95 ≤ 250ms 保持不变。真实云 embedding 曾测得 2257.86ms，批量后 915.23ms，仍未达到 250ms；这两份失败报告保留。另设 `rag_cloud_thresholds.json` 的 P95 ≤ 3000ms，质量门限相同，这是本轮新定的云接口工程预算。独立复测为 704.57ms，8 个真实模型样本含 2 个无答案题均通过，不能称为通过离线 250ms 门槛。

提交基线 `target_domain_rag_v2.json` 仅覆盖 schema 4 的离线检索；与真实模型候选比较时仅比较检索，不伪造历史模型基线。真实模型趋势须在相同数据集、模型、Prompt、检索源码和依赖摘要下重新 bootstrap。

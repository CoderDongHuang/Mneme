# 文档解析与 RAG

## 处理链路

1. Java 校验用户对知识库的所有权并保存原文件。
2. Java 创建文档元数据，调用 Python `/knowledge/ingest`。
3. Python 后台解析，任务状态为 `processing`。
4. 解析器按格式还原页码、章节、表格和正文。
5. 切片器保持结构化元素完整，对正文执行带重叠的语义段落切分。
6. Chroma 按用户和知识库隔离存储；SQLite FTS5 同步维护持久化词法索引。
7. 检索使用 Dense、FTS5 词法召回和 RRF；可通过配置懒加载 Cross Encoder。
8. Java 轮询任务状态并更新 `ready / failed` 与 chunk 数量。

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
- `RERANKER_ENABLED=true`、`RERANKER_PROVIDER=dashscope` 与 `RERANKER_MODEL=gte-rerank-v2`：使用现有 DashScope SDK 在线重排；也可将 provider 设为 `cross_encoder` 使用本地模型。失败时自动降级到 RRF。
- `VECTOR_SHARD_URLS=http://chroma-0:8000,http://chroma-1:8000`：按 `user_id + kb_id` 稳定哈希到独立 Chroma 节点；`VECTOR_SHARD_COUNT` 应与地址数量一致。

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
- `faithfulness_proxy`：Top-K 首片段包含标注关键事实的离线证据 proxy，不等价于 RAGAS/LLM Faithfulness。
- `citation_precision / citation_recall`：引用片段相关性和问题级证据覆盖率。
- `citation_metadata_completeness`：引用是否完整包含文档、页码、章节和内容类型。
- `p95_latency_ms`：检索 P95 延迟。
- `estimated_input_tokens / estimated_input_cost`：按字符近似 token 的输入成本估算；使用 `--input-cost-per-million` 指定价格。

离线运行示例：

```powershell
$env:MNEME_OFFLINE_EMBEDDINGS="true"
python python-agent/scripts/evaluate_rag.py --input-cost-per-million 0.15
```

当前评测结果应作为回归基线，而不是生产质量承诺；真实扫描 PDF、复杂表格、公式和跨页问题仍需人工标注与视觉评测。

# 文档解析与 RAG

## 处理链路

1. Java 校验用户对知识库的所有权并保存原文件。
2. Java 创建文档元数据，调用 Python `/knowledge/ingest`。
3. Python 后台解析，任务状态为 `processing`。
4. 解析器按格式还原页码、章节、表格和正文。
5. 切片器保持结构化元素完整，对正文执行带重叠的语义段落切分。
6. Chroma 按用户和知识库隔离存储。
7. Java 轮询任务状态并更新 `ready / failed` 与 chunk 数量。

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

## 生产评测建议

- 检索命中率、MRR、Recall@K。
- 页码和章节引用正确率。
- 表格行列保持率。
- OCR 字符错误率。
- 无依据回答比例与引用覆盖率。

## 内置基线评测

`python-agent/evaluation/rag_cases.json` 定义问题、期望来源和关键事实，`python-agent/scripts/evaluate_rag.py` 输出：

- `Hit@K`：Top-K 中是否命中正确来源和关键事实。
- `MRR`：正确片段的平均倒数排名。
- `citation_metadata_completeness`：引用是否完整包含文档、页码、章节和内容类型。

默认评测夹具是虚构的“星桥计划”，可以安全地在离线确定性 Embedding 模式运行。真实项目应按自己的资料类型扩充数据集。

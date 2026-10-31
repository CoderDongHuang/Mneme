# API 契约维护

## 引用来源

`python-agent/app/models/chat.py` 的 `Source` 是当前普通回答与 SSE `meta.sources` 的引用模型。两条接口通过同一个 `citation_sources` 边界生成来源，不各自维护字段。保留检索编号顺序；空片段不会导致后续 `[n]` 指向另一个来源。

从仓库根目录运行：

```shell
python python-agent/scripts/export_chat_contract.py
python python-agent/scripts/export_chat_contract.py --check
```

导出文件包括 `contracts/chat-source.schema.json`、跨端示例 `contracts/chat-source.examples.json`，以及前端使用的 `frontend/src/api/generated/chat-source.d.ts`。不要手工改导出文件。Python 全套测试执行 `--check`，检测源码模型与提交的 schema、类型及示例是否同步；Java 测试检查字段集合、拒绝 `Object` 隐藏类型，并读入和无损输出生成示例；浏览器 API 测试验证拆成单字节的 SSE 帧仍保留全部字段与 null。

坐标采用 `[left, top, right, bottom]`，四个有限数字，值位于 `[0, 1]`，左右、上下不得倒置。无坐标时为 `null`。检索库存储的逗号分隔字符串在 Python 出口转换；Gateway 读取旧会话引用时也兼容这种格式并输出数组。残缺、非数字、布尔值、非有限数和无效矩形降为 `null`，保留该引用的正文、文档、版本与其他元数据，不删除整条引用。

`frontend/e2e/citation-contract-real.spec.js` 在真实部署中上传 PDF，验证普通回答、流式回答、MySQL 持久引用、幂等重放和页面引用展示。使用独立测试账号，结束请求删除；不注入模型回答或伪造引用。

## 覆盖范围

本次覆盖引用来源这个业务边界。其余请求/响应、错误状态、可空值、枚举和 SSE 事件名及 payload 的完整契约仍须继续补齐；不能将上述来源检查视为整个 API 的契约检查。

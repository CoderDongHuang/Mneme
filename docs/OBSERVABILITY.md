# HTTP 与流式回答指标

Python 内部 `/metrics` 提供 Prometheus 指标。该端点不经过 Gateway 用户接口，不应公开暴露到公网。所有路径标签使用路由模板；不将用户、会话、请求正文、异常文本或任意取消原因作为标签。

| 指标 | 计时口径 |
| --- | --- |
| `mneme_python_http_request_duration_seconds` | 请求进入 ASGI 到响应 body 和资源清理结束；异常、取消也计入 |
| `mneme_python_http_response_headers_seconds` | 响应头成功交付给 ASGI server 的时间 |
| `mneme_python_sse_ttft_seconds` | 首个带数据的 `token` 事件完整交付时间，不包含仅收到 meta/响应头的流 |
| `mneme_python_sse_answer_duration_seconds{event="done\|error"}` | 回答终态事件交付时间，包含请求准备、检索、核验和终态前的处理；不是纯模型推理耗时 |
| `mneme_python_sse_duration_seconds` | 流的完整生命周期，包含关闭上游和清理；按 outcome、reason 区分 |
| `mneme_python_sse_ends_total` | 每个流恰好记录一次结束，用于完成率和中断率 |

`outcome` 为 `completed`、`client_disconnect`、`transport_error`、`cancelled`、`error`、`http_error` 或 `incomplete`。只有 done 和最终 body 发送成功且无异常才记 completed。`reason` 默认等于 outcome，已知阶段原因可为 model_timeout、model_error、grounding_failed、memory_failed、user_stopped；未知原因不会扩张标签。

当前浏览器停止按钮通过断开连接停止生成，服务端只能确定 client_disconnect，无法据此区分用户点击停止和网络断开。user_stopped 仅预留给显式业务信号，不能将所有断开伪报为用户停止。模型超时后成功发送降级回答可为 completed / model_timeout，表示传输完成，不表示模型成功。无 token 的流不产生 TTFT 样本；无终态事件的流不产生 answer_duration 样本。

示例 PromQL（无请求时比率无值；按实例聚合后再计算）：

```promql
# 5 分钟内传输中断比例，业务错误单独观察
sum(rate(mneme_python_sse_ends_total{outcome=~"client_disconnect|transport_error|cancelled|incomplete"}[5m]))
  / sum(rate(mneme_python_sse_ends_total[5m]))

# 首 Token p95
histogram_quantile(0.95, sum by (le, path) (rate(mneme_python_sse_ttft_seconds_bucket[5m])))

# 完整流 p95，包含中断的实际寿命
histogram_quantile(0.95, sum by (le, path) (rate(mneme_python_sse_duration_seconds_bucket[5m])))

# 按结束阶段检查故障
sum by (outcome, reason) (rate(mneme_python_sse_ends_total[5m]))
```

回归：`python -m pytest tests/test_http_lifecycle_metrics.py -q`。包含可控时钟区分响应头、TTFT、终态和最终清理，真实 Uvicorn/TCP 的 30 秒流，以及提前断开后的资源释放和中断指标。

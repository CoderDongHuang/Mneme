import base64
from typing import Any

from app.core.config import settings
from app.core.logging import setup_logger


logger = setup_logger("vision")


def describe_image(image_bytes: bytes, context: str) -> str:
    """Describe a document image with Qwen-VL when explicitly enabled."""
    if not settings.multimodal_enabled:
        return ""
    if not settings.dashscope_api_key:
        raise RuntimeError("启用多模态解析后必须配置 DASHSCOPE_API_KEY")

    from langchain_openai import ChatOpenAI

    client = ChatOpenAI(
        model=settings.multimodal_model,
        api_key=settings.dashscope_api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        temperature=0,
        timeout=60,
        max_retries=1,
    )
    encoded = base64.b64encode(image_bytes).decode("ascii")
    content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                "你是文档结构解析器。提取图片中的标题、正文、表格、公式、"
                "流程关系和图表结论。不要猜测看不清的内容，使用结构化纯文本输出。"
                f"文档位置：{context}"
            ),
        },
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{encoded}"},
        },
    ]
    response = client.invoke([{"role": "user", "content": content}])
    result = str(response.content).strip()
    logger.info("多模态图片解析完成: context=%s chars=%s", context, len(result))
    return result

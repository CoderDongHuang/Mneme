"""
pytest 共享 fixtures 和配置
"""
import os
import sys
import pytest

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# 测试前禁用 Chroma 遥测，避免日志噪音
os.environ["ANONYMIZED_TELEMETRY"] = "False"

# 使用本地持久化 Chroma（避免依赖外部服务）
os.environ.setdefault("CHROMA_HOST", "localhost")  # 触发 PersistentClient


@pytest.fixture
def sample_conversation():
    """一段包含偏好和学习进度的示例对话"""
    return [
        {"role": "user", "content": "帮我解释一下什么是反向传播"},
        {"role": "assistant", "content": "反向传播是神经网络中计算梯度的核心算法..."},
        {"role": "user", "content": "能不能用图表来说明？文字太多我看不懂"},
        {"role": "assistant", "content": "好的，我换一种方式...先画出网络结构，再标注梯度流向..."},
        {"role": "user", "content": "谢谢，这样清楚多了"},
    ]


@pytest.fixture
def weak_point_conversation():
    """一段暴露薄弱点的对话"""
    return [
        {"role": "user", "content": "什么是梯度下降？"},
        {"role": "assistant", "content": "梯度下降是一种优化算法..."},
        {"role": "user", "content": "我还是不太懂，能再解释一遍吗？"},
        {"role": "assistant", "content": "当然，我们从最基础的说起..."},
        {"role": "user", "content": "还是没完全理解，先跳过吧"},
    ]


@pytest.fixture
def empty_conversation():
    """空对话"""
    return []


@pytest.fixture
def mock_llm_response():
    """创建一个模拟的 LLM 响应对象"""
    class MockResponse:
        def __init__(self, content: str):
            self.content = content
    return MockResponse

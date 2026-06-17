# LangChain Tool 包装器目录
#
# 计划在此实现以下工具，供 LangGraph Agent 调用：
# - knowledge_tool.py: 知识库检索工具（封装 retriever.retrieve）
# - memory_tool.py:   记忆读写工具（封装 long_term_memory CRUD）
#
# 当前阶段 Agent 节点直接调用 retriever 和 memory 模块，
# 工具化封装留待后续阶段实现（便于扩展为 ReAct 模式）。

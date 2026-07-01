# MemoryStore：长期记忆，跨对话轮次持久化信息。
#
# 功能：
#   - save(key: str, value: str)         保存一条记忆（key-value）
#   - get(key: str) -> str | None        按 key 精确查找
#   - search(query: str) -> list[str]    语义相似度检索（需要嵌入向量支持）
#   - delete(key: str)                   删除一条记忆
#
# 存储后端（可插拔，通过接口抽象）：
#   - 简单实现：JSON 文件存储（适合开发/调试）
#   - 生产实现：向量数据库（如 ChromaDB、Qdrant）支持语义检索
#
# 向量检索实现要点：
#   - 写入时调用 embedding 模型（如 nomic-embed-text via Ollama）生成向量
#   - 检索时同样对 query 生成向量，计算余弦相似度，返回 top-k 结果

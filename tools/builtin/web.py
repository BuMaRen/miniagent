# 内置网络请求工具集。
#
# 实现以下工具函数：
#
#   http_get(url: str, headers: dict | None) -> str
#     发起 GET 请求，返回响应体文本（失败时返回错误字符串）
#
#   http_post(url: str, body: str, headers: dict | None) -> str
#     发起 POST 请求，body 为 JSON 字符串，返回响应体文本
#
#   fetch_webpage(url: str) -> str
#     获取网页 HTML 并提取纯文本内容（去掉标签），适合让 LLM 阅读网页内容
#     推荐使用 httpx + BeautifulSoup 实现
#
# 注意：
#   - 统一设置合理超时（如 10s），避免 Agent 卡住
#   - 响应内容过长时截断并附上截断提示

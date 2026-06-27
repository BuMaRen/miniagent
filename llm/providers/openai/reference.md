# OpenAI Chat Completions — Message 格式规范

## 公共字段

所有 message 对象都有：

| 字段 | 类型 | 必须 | 说明 |
|------|------|------|------|
| `role` | string | ✅ | `"system"` / `"user"` / `"assistant"` / `"tool"` |

---

## system

设置模型行为的系统提示词。

```json
{
  "role": "system",
  "content": "You are a helpful assistant."
}
```

| 字段 | 类型 | 必须 | 说明 |
|------|------|------|------|
| `content` | string \| array | ✅ | 提示词文本，或内容块数组 |
| `name` | string | ❌ | 区分多个 system message 时使用 |

---

## user

用户输入，支持纯文本或多模态内容。

```json
{ "role": "user", "content": "帮我分析这段代码。" }
```

多模态（文本 + 图片）：

```json
{
  "role": "user",
  "content": [
    { "type": "text", "text": "这张图里有什么？" },
    {
      "type": "image_url",
      "image_url": {
        "url": "https://example.com/image.png",
        "detail": "auto"
      }
    }
  ]
}
```

| 字段 | 类型 | 必须 | 说明 |
|------|------|------|------|
| `content` | string \| array | ✅ | 文本字符串，或内容块数组 |
| `name` | string | ❌ | 多用户场景区分身份 |

**内容块类型：**

| `type` | 额外字段 | 说明 |
|--------|----------|------|
| `"text"` | `text: string` | 纯文本 |
| `"image_url"` | `image_url: {url, detail?}` | 图片，`detail` 可选 `"auto"` / `"low"` / `"high"` |

---

## assistant

模型的回复，可包含文字内容和/或工具调用请求。

纯文字回复：

```json
{ "role": "assistant", "content": "好的，我来帮你分析。" }
```

携带工具调用（此时 `content` 通常为 `null`）：

```json
{
  "role": "assistant",
  "content": null,
  "tool_calls": [
    {
      "id": "call_abc123",
      "type": "function",
      "function": {
        "name": "read_file",
        "arguments": "{\"path\": \"/tmp/foo.txt\"}"
      }
    }
  ]
}
```

| 字段 | 类型 | 必须 | 说明 |
|------|------|------|------|
| `content` | string \| null | ❌ | 文字回复，有 `tool_calls` 时通常为 `null` |
| `tool_calls` | array | ❌ | 工具调用列表，见下方 |
| `refusal` | string \| null | ❌ | 模型拒绝原因（内容安全触发时出现） |
| `name` | string | ❌ | 多 assistant 场景区分身份 |

**tool_calls 元素结构：**

| 字段 | 类型 | 必须 | 说明 |
|------|------|------|------|
| `id` | string | ✅ | 工具调用的唯一 ID，回传结果时必须对应 |
| `type` | string | ✅ | 固定为 `"function"` |
| `function.name` | string | ✅ | 函数名 |
| `function.arguments` | string | ✅ | JSON 字符串（不是对象，是字符串） |

---

## tool

工具执行结果，必须跟在触发它的 assistant message 之后。

```json
{
  "role": "tool",
  "tool_call_id": "call_abc123",
  "content": "文件内容：Hello World"
}
```

| 字段 | 类型 | 必须 | 说明 |
|------|------|------|------|
| `tool_call_id` | string | ✅ | 对应 assistant `tool_calls[i].id` |
| `content` | string \| array | ✅ | 工具返回值，通常序列化为字符串 |

---

## 多工具调用的 messages 顺序

一次 assistant 响应可以同时请求多个工具，每个工具结果独立回传：

```json
[
  { "role": "user", "content": "读取 a.txt 和 b.txt" },
  {
    "role": "assistant",
    "content": null,
    "tool_calls": [
      { "id": "call_1", "type": "function", "function": { "name": "read_file", "arguments": "{\"path\":\"a.txt\"}" } },
      { "id": "call_2", "type": "function", "function": { "name": "read_file", "arguments": "{\"path\":\"b.txt\"}" } }
    ]
  },
  { "role": "tool", "tool_call_id": "call_1", "content": "内容A" },
  { "role": "tool", "tool_call_id": "call_2", "content": "内容B" }
]
```

所有 tool message 必须在下一个 assistant/user message 之前出现，且 `tool_call_id` 必须全部对应。

---

## 模型响应（ChatCompletion）

调用 `client.chat.completions.create()` 后返回的顶层对象。

```json
{
  "id": "chatcmpl-abc123",
  "object": "chat.completion",
  "created": 1719000000,
  "model": "gpt-4o",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": null,
        "tool_calls": [
          {
            "id": "call_abc123",
            "type": "function",
            "function": {
              "name": "read_file",
              "arguments": "{\"path\": \"/tmp/foo.txt\"}"
            }
          }
        ]
      },
      "finish_reason": "tool_calls",
      "logprobs": null
    }
  ],
  "usage": {
    "prompt_tokens": 120,
    "completion_tokens": 40,
    "total_tokens": 160,
    "prompt_tokens_details": { "cached_tokens": 0 },
    "completion_tokens_details": { "reasoning_tokens": 0 }
  },
  "system_fingerprint": "fp_abc123"
}
```

**顶层字段：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 本次请求的唯一 ID |
| `object` | string | 固定为 `"chat.completion"` |
| `created` | integer | Unix 时间戳 |
| `model` | string | 实际使用的模型名称（可能与请求的别名不同） |
| `choices` | array | 模型的回复列表，通常只有一个元素 |
| `usage` | object | Token 用量统计 |
| `system_fingerprint` | string \| null | 后端配置指纹，用于判断结果是否可复现 |

**choices 元素字段：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `index` | integer | 序号，通常为 0 |
| `message` | object | 模型生成的 assistant message（结构同上方 assistant 节） |
| `finish_reason` | string | 停止原因，驱动 agent loop 的核心字段（见下） |
| `logprobs` | object \| null | Token 概率信息，默认为 null，需显式请求才返回 |

**finish_reason 取值：**

| 值 | 含义 | agent 应对 |
|----|------|-----------|
| `"stop"` | 模型正常结束输出 | 返回最终答案给用户 |
| `"tool_calls"` | 模型请求调用工具 | 执行工具，将结果 append 进 messages，继续循环 |
| `"length"` | 达到 `max_tokens` 被截断 | 上下文压缩或报错 |
| `"content_filter"` | 内容被安全策略过滤 | 报错或提示用户 |

**usage 字段：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `prompt_tokens` | integer | 输入消耗的 token 数（含历史 messages + tools 定义） |
| `completion_tokens` | integer | 输出消耗的 token 数 |
| `total_tokens` | integer | 总消耗 = prompt + completion |
| `prompt_tokens_details.cached_tokens` | integer | 命中 prompt cache 的 token 数（计费打折） |
| `completion_tokens_details.reasoning_tokens` | integer | o 系列模型内部推理消耗的 token 数（不出现在 content 里） |

**访问模式（Python SDK）：**

```python
response = client.chat.completions.create(...)

choice = response.choices[0]
finish_reason = choice.finish_reason          # "stop" / "tool_calls" / ...
content = choice.message.content              # str | None
tool_calls = choice.message.tool_calls        # list | None

prompt_tokens = response.usage.prompt_tokens
total_tokens = response.usage.total_tokens
```

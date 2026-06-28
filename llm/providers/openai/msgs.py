from llm.data.message import Message
from tools.schema import ToolCall

def construct_messages(msg: Message) -> dict:
    if msg.role == "user":
        return user_message(msg.content)
    elif msg.role == "system":
        return system_message(msg.content)
    elif msg.role == "assistant":
        return assistant_message(msg.content, msg.tool_calls)
    elif msg.role == "tool":
        if not msg.tool_call_id:
            raise ValueError("tool message must have tool_call_id")
        return tool_message(msg.content, msg.tool_call_id)
    raise ValueError(f"Unknown role '{msg.role}'.")


def system_message(content: str | list) -> dict:
    """
    构造一个系统消息对象。
    """
    return {
        "role": "system",
        "content": content,
    }


def user_message(content: str | list) -> dict:
    """
    构造一个用户消息对象。
    """
    return {
        "role": "user",
        "content": content,
    }


def assistant_message(content: str | list, tool_calls: list[ToolCall] = None) -> dict:
    """
    构造一个助手消息对象。
    """
    msg = {
        "role": "assistant",
        "content": content,
    }
    if tool_calls:
        msg["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": call.arguments,
                },
            }
            for call in tool_calls
        ]
    return msg


def tool_message(content: str | list, tool_call_id: str) -> dict:
    """
    构造一个工具消息对象。
    """
    return {
        "role": "tool",
        "content": content,
        "tool_call_id": tool_call_id,
    }


def choice_to_message(choice: dict) -> Message:
    msg = choice["message"]
    return Message(
        role=msg["role"],
        content=msg.get("content"),
        tool_calls=[
            ToolCall(
                id=call["id"],
                name=call["function"]["name"],
                arguments=call["function"]["arguments"],
            )
            for call in msg.get("tool_calls") or []
        ],
        tool_call_id=msg.get("tool_call_id"),
    )

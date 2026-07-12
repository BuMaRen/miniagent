# AgentLoop：agentic loop 的核心控制流，与 Agent 基类解耦。
#
# 职责：
#   - 实现标准 agentic loop：调用 LLM -> 判断是否有工具请求 -> 执行工具 -> 再次调用 LLM -> ...
#   - 维护最大循环深度（max_steps），超出时中断并返回
#   - 每轮调用前后触发 LifecycleHooks（参见 hooks/lifecycle.py）
#   - 循环结束条件：模型不再请求工具调用，或 max_steps 达到上限
#
# 设计原则：
#   - 不直接调用任何 provider SDK，通过 LLMClient 抽象层交互
#   - 工具调用完成后【不注入额外 user 消息】，直接将 tool 结果追加到 messages 后再次调用
#     （针对不够健壮的本地模型，可在 AgentConfig 中配置 force_continue_prompt 来注入提示）
#   - 返回值统一为 LoopResult 数据类，包含最终答案文本、调用轮次、工具调用列表

from flag.debug import DEBUG_LOG
from llm.base.client import LLMClient
from llm.data.message import Message
from state.runtime import AgentRuntime
from tools.schema import ToolSchema
from tools.executor import ToolExecutor


def agent_loop(
    client: LLMClient,
    tools: list[ToolSchema],
    executor: ToolExecutor,
    messages: list[Message],
    state: AgentRuntime | None = None,
    verbose: bool = True,
):
    turn_messages = messages
    log = DEBUG_LOG and verbose
    # 部分本地模型在收到工具结果后仍会重复发起同一个调用而不是结束本轮，
    # 这里按 (name, arguments) 缓存已执行过的调用结果，避免重复执行造成
    # 副作用叠加（例如同一行的 record 被反复计数）。
    seen_calls: dict[tuple[str, str], str] = {}

    # 工具调用过程不记录，上下文只记录单次响应
    for _ in range(10):
        if log:
            print(f"processing messages: {turn_messages[-1]}")
        resp = client.chat(messages=turn_messages, tools=tools)
        if resp.finish_reason == "length":
            if log:
                print("[WARNING] LLM response truncated due to length/context limit.")
            return "[WARNING] LLM response truncated due to length/context limit."
        elif resp.finish_reason == "content_filter":
            if log:
                print("[WARNING] LLM response blocked by content filter.")
            return "[WARNING] LLM response blocked by content filter."
        elif resp.finish_reason == "stop":
            # 打印结果的时候将字体颜色改为绿色，表示这是本轮答案
            if log:
                print("\033[92mAnswer:\n" + resp.message.content + "\033[0m")
            return resp.message.content

        # 蓝色打印model返回结果，包括tool调用请求
        if log:
            print("\033[94mModel response:\n" + resp.message.content + "\033[0m")

        turn_messages.append(resp.message)
        for call in resp.message.tool_calls or []:
            cache_key = (call.name, call.arguments)
            if cache_key in seen_calls:
                if log:
                    print(
                        f"Duplicate tool call detected, reusing cached result: {call.name} with args: {call.arguments}"
                    )
                tool_resp = seen_calls[cache_key]
            else:
                if log:
                    print(f"Executing tool call: {call.name} with args: {call.arguments}")
                tool_resp = executor.execute(call)
                seen_calls[cache_key] = tool_resp
            turn_messages.append(
                Message(
                    role="tool",
                    content=tool_resp,
                    tool_call_id=call.id,
                )
            )
            if state:
                state.record_tool_call(
                    name=call.name, args=call.arguments, result=tool_resp
                )
    # 如果模型比较傻，需要在这里注入一个强制继续的提示，告诉模型继续回答
    if log:
        print(
            "[WARNING] Agent loop reached max steps without finishing. Consider increasing max_steps or checking model/tool behavior."
        )
    return "[WARNING] Agent loop reached max steps without finishing. Consider increasing max_steps or checking model/tool behavior."

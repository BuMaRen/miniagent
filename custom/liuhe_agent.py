import time
from concurrent.futures import ThreadPoolExecutor

from llm.base.client import LLMClient
from llm.data.message import Message
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry
from custom.prompt import system_prompt
from custom.pre_process import pre_merge_input, split_input, sensitive_transfer, normalize_delimiters
from custom.record import record_tools, summary_record


class LiuHeAgent:

    def __init__(self, client: LLMClient):
        self.client = client
        self.tool_registry = ToolRegistry()
        for func, schema in record_tools:
            self.tool_registry.register(schema.name, func, schema)
        self.tool_executor = ToolExecutor(self.tool_registry)
        self.uuids = set()  # 用于记录已处理的 uuid，避免重复汇总

    def _chat(self, uuid: str, user_input: str) -> str:
        """_chat - 单次调用模型解析一行输入，并执行模型请求的工具调用

        不走多轮 agent_loop，只发起一次请求：模型应当直接调用 record 工具
        完成记录，工具的执行结果即为本次返回值。

        Args:
            uuid (str): 用户的唯一标识符
            user_input (str): 用户输入的消息

        Returns:
            str: 工具调用结果；若模型没有调用工具，则返回模型的文本回复。
        """
        sys_prompt_content = [{
            "type": "text",
            "text": system_prompt,
            "cache_control": {"type": "ephemeral"},
        }]
        if uuid in self.uuids:
            sys_prompt_content = system_prompt
        messages = [
            Message(role="system", content=sys_prompt_content),
            Message(
                role="user",
                content=f"订单编号（uuid）为：{uuid}\n{user_input}",
            ),
        ]
        # 淡黄色打印当前处理的内容，便于定位失败是哪一行输入引发的
        tag = user_input[:12].replace("\n", " ")
        # print(f"\033[93m处理内容：{user_input}\033[0m")

        # 用流式接口发起请求：非流式模式下服务端要等生成全部完成才会返回第一个字节，
        # 遇到 qwen 思考模式这种会输出大量 reasoning token 的情况，容易长时间没有任何
        # 反馈、也更容易触发底层 httpx 的 idle read timeout；流式则每个 chunk 都能重置
        # idle 计时、也能让我们看到实时生成进度。
        start = time.monotonic()
        first_token_at = None

        def on_delta(text: str):
            nonlocal first_token_at
            if first_token_at is None:
                first_token_at = time.monotonic()
                print(
                    f"\n\033[93m[{tag}] 首 token 耗时 {first_token_at - start:.2f}s\033[0m"
                )
            print(f"\033[93m[{tag}]\033[0m {text}", end="", flush=True)

        resp = self.client.stream_chat(
            messages=messages,
            tools=self.tool_registry.schemas(),
            on_delta=on_delta,
            # 这是确定性的信息抽取 + 工具调用任务，不需要思考过程；关闭思考模式
            # 避免 qwen 生成大量无谓的 reasoning token 拖长耗时（支持工程师建议）
            extra_body={"enable_thinking": True},
            # 兜底：即使思考模式关闭失败/模型仍然跑飞，也不会无限生成下去
            max_tokens=2048,
        )
        print()
        # end = time.monotonic()
        # ttft = (first_token_at or end) - start
        # print(
        #     f"\033[93m[{tag}] 首token {ttft:.2f}s / 总耗时 {end - start:.2f}s\033[0m"
        # )
        
        # 淡黄色打印模型原始响应，便于排查工具未被调用/参数错误等失败原因
        # print(f"\033[93mresp：{resp}\033[0m")

        tool_calls = resp.message.tool_calls or []
        if not tool_calls:
            result = resp.message.content
        else:
            # 粉色打印本次调用的原始输入行与处理后的结果，便于逐条核对
            print(f"\033[95muuid={uuid} 原始行：{user_input}\033[0m")
            results = [self.tool_executor.execute(call) for call in tool_calls]
            result = "\n".join(results)
        return result

    def run(self, user_input: str) -> str:
        """Run the LiuHeAgent with the given user input.

        第一行请求单独同步发起，用于把 system_prompt 写入模型侧的 prompt cache；
        写缓存完成后，其余行才并发发起，都能命中缓存。

        Args:
            user_input (str): The user's input message.

        Returns:
            str: 按方案归属（惊/开）分开的汇总结果。
        """
        uuid = str(int(time.time() * 1000))
        safety_input = sensitive_transfer(normalize_delimiters(user_input))
        split_lines = split_input(safety_input)
        # split_lines = pre_merge_input(split_lines)

        if split_lines:
            first_resp = self._chat(uuid, split_lines[0])
            print(f"\033[34m{first_resp}\033[0m")
            self.uuids.add(uuid)  # 首次请求已建立缓存，标记 uuid 后续走非 cache_control 分支

            rest_lines = split_lines[1:]
            if rest_lines:
                with ThreadPoolExecutor(max_workers=len(rest_lines)) as executor:
                    for resp in executor.map(lambda line: self._chat(uuid, line), rest_lines):
                        # 蓝色字体打印
                        print(f"\033[34m{resp}\033[0m")

        summary = summary_record(uuid)
        # 绿色字体打印
        print(f"\033[32m汇总结果：\n{summary}\033[0m")
        return summary

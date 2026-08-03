"""从声明式定义(stages.yaml)构建 Node —— 把节点装配这件事从场景侧下沉到框架。

`workflow.yaml` 声明的是**流程结构**(谁套谁、循环到什么时候为止,见
engine/workflow.py 的 Workflow.from_spec);这里声明的是**节点本身**:每个 Stage
由谁执行、读写哪些状态切片、输出要符合哪份契约。两份定义合起来,场景方就不必再
手写 `build_xxx_stage()` 这类装配胶水了。

## YAML 长什么样

顶层是 `{节点名: 节点定义}`(外加一个可选的保留键 `defaults`):

    defaults:                       # 可选:合并进每个 agent executor 的缺省字段
      executor:
        max_steps: 8

    input_parsing:                  # ① executor 是字符串 -> 按名查 ExecutorRegistry
      executor: input_parsing_executor
      writes:
        - story_bible.meta

    concept_expansion:              # ② executor 是 dict -> 现场装配一个 Agent
      executor:
        model: claude-sonnet-latest
        tools:
          - research
        output_schema: concept_expansion_output
        prompt: "@concept_expansion_prompt"
      reads:
        - story_bible.meta
      writes:
        - story_bible.meta

    confirm_outline:                # ③ checkpoint -> 人工断点(引擎原语)
      checkpoint:
        prompt: 大纲已通过 AI 评审,请确认……
        resume_input_schema: critic_output

    chapter_critic:                 # ④ wrap -> 节点建好后按名套一层包装
      executor: {...}
      wrap: chapter_critic_status_writeback   # 或 wrap: [a, b] 按序应用多个

`wrap` 是节点建好之后(不管是 executor 还是 checkpoint 分支建出来的)再做的一层
包装,用来表达声明式定义本身表达不了的副作用——包装函数按 `engine.stage.node_wrapper`
装饰器登记进 `NodeWrapperRegistry`,取代过去场景侧在自己的 build_node_registry 里
手写 `registry.replace(SomeWrapper(registry.get("目标节点名")))` 这行接线。

## 引用规则:什么时候写裸字符串,什么时候写 "@"

- **executor / schema / toolset 本身就是对象**,YAML 里写得下的只有它们的名字,
  所以裸字符串一律视为"去对应注册表按名检索":`executor: input_parsing_executor`
  查 engine.stage.ExecutorRegistry(用 @executor 装饰器登记),
  `output_schema: critic_output` 查 state.schema.SchemaRegistry,
  `tools: [research]` 查 agent.toolset.ToolSetRegistry。
- **prompt 的值本身就是文本**,裸字符串没法区分"正文"和"名字",所以引用要显式写成
  `"@名字"`(去 prompts.PromptRegistry 检索);不带 @ 的就是字面量正文。

⚠️ `@` 是 YAML 的保留指示符,**不能**作为 plain scalar 的首字符——`prompt: @foo`
会让 yaml.safe_load 直接报 "found character '@' that cannot start any token"。
必须加引号写成 `prompt: "@foo"`。

## 输出格式那一段谁来写

agent executor 必须声明 output_schema(既用于 Provider 的结构化输出,也用于
Stage 的输出校验),因此"输出格式示例"这段文本框架能自己生成,不必在提示词里手抄:
提示词里写一行 `@output_schema_example` 就会被替换成
`StateSchema.to_prompt_example()` 的结果;没写这行时,框架把它追加到提示词末尾。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import yaml

from agent.agent import Agent
from agent.memory import ConversationMemory
from agent.toolset import ToolSetRegistry
from agent.toolset import default_registry as default_toolset_registry
from engine.primitives.checkpoint import Checkpoint
from engine.stage import ExecutorRegistry, Node, NodeWrapperRegistry, Stage
from engine.stage import default_registry as default_executor_registry
from engine.stage import default_wrapper_registry
from engine.workflow import NodeRegistry
from llm.client import LLMClient
from prompts.registry import PromptRegistry, parse_ref
from prompts.registry import default_registry as default_prompt_registry
from state.schema import SchemaRegistry, StateSchema
from state.schema import default_registry as default_schema_registry
from tools.registry import ToolRegistry

# 按 (节点名, 生效 model) 给出一个 LLMClient。model 为 None 表示"没人指定过",
# 由工厂自行决定默认模型(见 scenarios/novel/run.py 的实现)。
ClientFactory = Callable[[str, str | None], LLMClient]

# 顶层保留键:不是节点名,而是各 agent executor 的缺省字段。
DEFAULTS_KEY = "defaults"

# 提示词里代表"这里贴 output_schema 的示例"的占位符名(用法:单起一行写
# `@output_schema_example`)。
OUTPUT_SCHEMA_EXAMPLE = "output_schema_example"

# 提示词里没写上面那个占位符时,自动追加的一段的抬头。
_OUTPUT_FORMAT_HEADER = "输出格式(严格输出 JSON,不要加 markdown 代码块):"

# 内部哨兵:先把占位符替换成它,借此判断提示词里到底有没有用到这个占位符
# (用不到就走"自动追加"),再换成真正的示例文本。
_EXAMPLE_SENTINEL = "\x00output_schema_example\x00"

_NODE_KEYS = {"executor", "checkpoint", "reads", "writes", "input_schema", "output_schema", "wrap"}
_AGENT_KEYS = {"model", "tools", "toolsets", "prompt", "output_schema", "max_steps"}
_CHECKPOINT_KEYS = {"prompt", "resume_input_schema"}


class SpecError(ValueError):
    """stages.yaml 的结构/引用错误。属 ValueError 便于上层统一捕获。"""


def load_spec(path: str | Path) -> dict[str, Any]:
    """读一份 stages.yaml,返回 build_node_registry 期望的 dict 结构。"""
    with open(path, "r", encoding="utf-8") as f:
        spec = yaml.safe_load(f) or {}
    if not isinstance(spec, dict):
        raise SpecError(f"{path}: 顶层须是 {{节点名: 节点定义}} 的映射,得到 {type(spec).__name__}")
    return spec


class NodeBuilder:
    """把节点定义编译成 Node。

    四张注册表都可以单独替换(测试里常这么做);缺省用各自模块的 default_registry,
    也就是场景方用 @executor 装饰器 / load_dir() 登记进去的那一张。
    """

    def __init__(
        self,
        *,
        client_factory: ClientFactory | None = None,
        stage_models: dict[str, str] | None = None,
        executors: ExecutorRegistry | None = None,
        prompts: PromptRegistry | None = None,
        schemas: SchemaRegistry | None = None,
        toolsets: ToolSetRegistry | None = None,
        wrappers: NodeWrapperRegistry | None = None,
        defaults: dict[str, Any] | None = None,
    ) -> None:
        self.client_factory = client_factory
        self.stage_models = stage_models or {}
        self.executors = executors if executors is not None else default_executor_registry
        self.prompts = prompts if prompts is not None else default_prompt_registry
        self.schemas = schemas if schemas is not None else default_schema_registry
        self.toolsets = toolsets if toolsets is not None else default_toolset_registry
        self.wrappers = wrappers if wrappers is not None else default_wrapper_registry
        self.defaults = defaults or {}

    # -- 单个节点 ---------------------------------------------------------------

    def build(self, name: str, spec: Any) -> Node:
        """按节点定义建出 Stage 或 Checkpoint,再应用 `wrap` 声明的包装(若有)。"""
        if not isinstance(spec, dict):
            raise SpecError(f"节点 {name!r}: 定义须是 dict,得到 {spec!r}")
        unknown = set(spec) - _NODE_KEYS
        if unknown:
            raise SpecError(
                f"节点 {name!r}: 未知字段 {sorted(unknown)};可用字段: {sorted(_NODE_KEYS)}"
            )
        if "checkpoint" in spec:
            if "executor" in spec:
                raise SpecError(f"节点 {name!r}: checkpoint 与 executor 只能二选一")
            node = self._build_checkpoint(name, spec["checkpoint"])
        elif "executor" not in spec:
            raise SpecError(f"节点 {name!r}: 缺少 'executor'(或 'checkpoint')")
        else:
            node = self._build_stage(name, spec)
        return self._apply_wraps(name, node, spec.get("wrap"))

    def _apply_wraps(self, name: str, node: Node, value: Any) -> Node:
        if value is None:
            return node
        names = [value] if isinstance(value, str) else value
        if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
            raise SpecError(
                f"节点 {name!r} 的 wrap: 须是已注册的包装器名(str)或其列表,得到 {value!r}"
            )
        for wrapper_name in names:
            try:
                wrapper = self.wrappers.get(wrapper_name)
            except KeyError as err:
                raise SpecError(f"节点 {name!r} 的 wrap: {err.args[0]}") from None
            node = wrapper(node)
        return node

    def _build_stage(self, name: str, spec: dict[str, Any]) -> Stage:
        output_schema = self._schema(name, "output_schema", spec.get("output_schema"))
        raw_executor = spec["executor"]
        if isinstance(raw_executor, str):
            try:
                executor = self.executors.get(raw_executor)
            except KeyError as err:
                raise SpecError(f"节点 {name!r} 的 executor: {err.args[0]}") from None
        elif isinstance(raw_executor, dict):
            # agent 的 output_schema 与 Stage 的往往是同一份(既开结构化输出、又校验
            # 产出),所以两处只写一处即可:节点级没写就沿用 agent 声明的那份。
            agent, output_schema = self._build_agent(name, raw_executor, output_schema)
            executor = agent.run
        else:
            raise SpecError(
                f"节点 {name!r}: executor 须是已注册的 executor 名(str)或 agent 定义(dict),"
                f"得到 {raw_executor!r}"
            )
        return Stage(
            name=name,
            executor=executor,
            input_schema=self._schema(name, "input_schema", spec.get("input_schema")),
            output_schema=output_schema,
            reads=self._paths(name, "reads", spec.get("reads")),
            writes=self._paths(name, "writes", spec.get("writes")),
        )

    def _build_agent(
        self, name: str, spec: dict[str, Any], stage_output_schema: StateSchema | None
    ) -> tuple[Agent, StateSchema]:
        spec = {**self.defaults.get("executor", {}), **spec}
        unknown = set(spec) - _AGENT_KEYS
        if unknown:
            raise SpecError(
                f"节点 {name!r} 的 executor: 未知字段 {sorted(unknown)};"
                f"可用字段: {sorted(_AGENT_KEYS)}"
            )

        # output_schema 对 agent 是必填的:它既是 Provider 结构化输出的契约,也是
        # 提示词里"输出格式"那段示例的来源。节点级已经声明过就不必再写一遍。
        output_schema = (
            self._schema(name, "executor.output_schema", spec.get("output_schema"))
            or stage_output_schema
        )
        if output_schema is None:
            raise SpecError(
                f"节点 {name!r}: agent executor 必须声明 output_schema(用于结构化输出)"
            )

        if "prompt" not in spec:
            raise SpecError(f"节点 {name!r}: agent executor 缺少 'prompt'")
        if self.client_factory is None:
            raise SpecError(
                f"节点 {name!r} 需要 LLMClient,但没有提供 client_factory"
            )

        # model 的优先级:workflow.yaml 上标注/继承下来的(编排层)优先于
        # stages.yaml 里节点自带的默认值。两处都没有时传 None,由 client_factory
        # 退回它自己的默认模型。
        model = self.stage_models.get(name) or spec.get("model")

        agent = Agent(
            client=self.client_factory(name, model),
            memory=ConversationMemory(
                system_prompt=self._prompt(name, spec["prompt"], output_schema)
            ),
            # 每个 Agent 独占一张 ToolRegistry:工具是"挂在这个 Agent 上"的,
            # 共用全局表会让所有 Stage 互相看见对方的工具。
            registry=ToolRegistry(),
            output_schema=output_schema,
        )
        if "max_steps" in spec:
            agent.max_steps = spec["max_steps"]
        for toolset_name in self._toolset_names(name, spec):
            try:
                agent.load_toolset(self.toolsets.get(toolset_name))
            except KeyError as err:
                raise SpecError(f"节点 {name!r}: {err.args[0]}") from None
        return agent, output_schema

    def _build_checkpoint(self, name: str, spec: Any) -> Checkpoint:
        if spec is None:
            spec = {}
        if not isinstance(spec, dict):
            raise SpecError(f"节点 {name!r}: checkpoint 的值须是 dict(或留空),得到 {spec!r}")
        unknown = set(spec) - _CHECKPOINT_KEYS
        if unknown:
            raise SpecError(
                f"节点 {name!r} 的 checkpoint: 未知字段 {sorted(unknown)};"
                f"可用字段: {sorted(_CHECKPOINT_KEYS)}"
            )
        prompt = spec.get("prompt")
        return Checkpoint(
            name=name,
            # 这里的 prompt 是给**人**看的一句话(不是 LLM 的 system prompt),
            # 但同样支持 "@名字" 引用——长一点的说明也该能放进 prompt 文件里。
            prompt=None if prompt is None else self._prompt(name, prompt, None),
            resume_input_schema=self._schema(
                name, "checkpoint.resume_input_schema", spec.get("resume_input_schema")
            ),
        )

    # -- 各类引用的解析 ---------------------------------------------------------

    def _schema(self, node: str, field: str, value: Any) -> StateSchema | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise SpecError(f"节点 {node!r} 的 {field}: 须是已注册的 schema 名(str),得到 {value!r}")
        try:
            return self.schemas.get(value)
        except Exception as err:  # SchemaError:未注册,带候选清单
            raise SpecError(f"节点 {node!r} 的 {field}: {err}") from None

    @staticmethod
    def _paths(node: str, field: str, value: Any) -> tuple[str, ...]:
        """reads/writes:一条状态路径的字符串,或它们的列表。"""
        if value is None:
            return ()
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list) or not all(isinstance(p, str) for p in value):
            raise SpecError(f"节点 {node!r} 的 {field}: 须是状态路径(str)的列表,得到 {value!r}")
        return tuple(value)

    def _toolset_names(self, node: str, spec: dict[str, Any]) -> list[str]:
        # tools / toolsets 是同一件事的两种叫法(挂载的单位始终是 ToolSet)。
        names = spec.get("tools", spec.get("toolsets")) or []
        if isinstance(names, str):
            names = [names]
        if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
            raise SpecError(f"节点 {node!r} 的 tools: 须是工具集名的列表,得到 {names!r}")
        return names

    def _prompt(self, node: str, value: Any, output_schema: StateSchema | None) -> str:
        if not isinstance(value, str):
            raise SpecError(f"节点 {node!r} 的 prompt: 须是字符串(\"@名字\" 或字面量),得到 {value!r}")
        placeholders = {OUTPUT_SCHEMA_EXAMPLE: _EXAMPLE_SENTINEL}
        ref = parse_ref(value)
        try:
            text = (
                self.prompts.get(ref, placeholders)
                if ref is not None
                else self.prompts.render(value, placeholders)
            )
        except Exception as err:  # PromptError:未注册 / 循环引用
            raise SpecError(f"节点 {node!r} 的 prompt: {err}") from None
        return _fill_output_example(text, output_schema)


def _fill_output_example(text: str, output_schema: StateSchema | None) -> str:
    """把提示词里的输出格式占位符换成真正的示例;没写占位符就追加到末尾。"""
    if output_schema is None:
        return text.replace(_EXAMPLE_SENTINEL, "")
    example = output_schema.to_prompt_example()
    if _EXAMPLE_SENTINEL in text:
        return text.replace(_EXAMPLE_SENTINEL, example)
    return f"{text.rstrip()}\n\n{_OUTPUT_FORMAT_HEADER}\n{example}\n"


def build_node_registry(
    spec: dict[str, Any] | str | Path,
    *,
    client_factory: ClientFactory | None = None,
    stage_models: dict[str, str] | None = None,
    executors: ExecutorRegistry | None = None,
    prompts: PromptRegistry | None = None,
    schemas: SchemaRegistry | None = None,
    toolsets: ToolSetRegistry | None = None,
    wrappers: NodeWrapperRegistry | None = None,
) -> NodeRegistry:
    """把一份 stages 定义(dict 或 YAML 路径)编译成 NodeRegistry。

    产出的 registry 正是 engine.workflow.Workflow.from_spec 需要的那张表:
    workflow.yaml 里按名引用的每个节点都能在这里查到。

    Args:
        spec: stages.yaml 的路径,或已经 load 好的 dict。
        client_factory: 按 (节点名, model) 取 LLMClient;只要有一个 agent
            executor 就必须提供。
        stage_models: workflow.yaml 解析出的 {节点名: model}(见
            engine.workflow.Workflow.resolve_stage_models),优先于节点自带的 model。
        executors / prompts / schemas / toolsets / wrappers: 五张注册表,缺省用
            各模块的 default_registry。
    """
    if isinstance(spec, (str, Path)):
        spec = load_spec(spec)
    builder = NodeBuilder(
        client_factory=client_factory,
        stage_models=stage_models,
        executors=executors,
        prompts=prompts,
        schemas=schemas,
        toolsets=toolsets,
        wrappers=wrappers,
        defaults=spec.get(DEFAULTS_KEY) or {},
    )
    registry = NodeRegistry()
    for name, node_spec in spec.items():
        if name == DEFAULTS_KEY:
            continue
        registry.register(builder.build(name, node_spec))
    return registry

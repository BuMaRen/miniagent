"""Scenario —— 按目录约定,把一个场景包组装成可运行的 Workflow。

场景方(如 scenarios/novel/)过去要手写三份纯粘合代码:一份 state_schema.py
(StateSchema.from_yaml + load_types)、一份 workflow.py(读 workflow.yaml ->
Workflow.resolve_stage_models -> 自己的 build_node_registry -> Workflow.from_spec ->
挂 state_schema),以及 stages.py 末尾"把 prompts/schemas/toolsets 三个目录登记进
各自全局注册表"的组装代码。这些步骤"读哪个文件、调哪个框架函数"是完全确定的,不含
任何场景语义,理应下沉到这里——场景方只需要按下面的目录约定摆好文件,在包的
__init__.py 里写一行 `SCENARIO = Scenario.from_package(__name__)`。

目录约定(均相对场景包目录,即调用 from_package 那个包所在的目录):

    state_schema.yaml   必需。场景的共享状态结构(见 state/schema.py 的 YAML DSL)。
    stages.yaml          必需。交给 engine.spec.build_node_registry 编译成 NodeRegistry。
    workflow.yaml         必需。交给 engine.workflow.Workflow.from_spec 编译成 Workflow。
    prompts/*.prompt     可选。存在则整目录交给 prompts.load_dir。
    schemas/*.yaml       可选。存在则整目录交给 SchemaRegistry.load_dir,借用
                          state_schema.yaml 的 types: 具名类型表(见 state/schema.py
                          load_types 的说明)。
    toolsets/*.py        可选。该子包下每个模块顶层的 agent.toolset.ToolSet 实例会被
                          自动发现并登记——ToolSet 只是数据,不需要装饰器,直接
                          isinstance 扫描即可,场景方不必再手写注册代码。
    executors.py         可选。存在则被 import 一次,用来触发场景方用
                          engine.stage.executor / engine.stage.node_wrapper 装饰器
                          登记纯函数 executor、节点包装工厂这两类"声明式定义表达不了"
                          的 Python——这是场景方在这套约定下唯一还需要手写的代码。

框架层不认识场景语义:本模块只依赖 engine/ 自身与 state/agent/prompts,不 import
任何 scenarios.* 包。
"""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

import prompts as prompt_module
from agent.toolset import ToolSet
from agent.toolset import default_registry as default_toolset_registry
from engine.spec import ClientFactory, build_node_registry as build_node_registry_from_spec
from engine.workflow import NodeRegistry, Workflow
from state import schema as schema_module
from state.schema import StateSchema, load_types


@dataclass
class Scenario:
    """一个按上述目录约定装配好的场景。

    Attributes:
        package:       场景包的 dotted module 名(如 "scenarios.novel")。
        root:          场景包所在目录。
        state_schema:  场景的 StateSchema(已登记进 state.schema.default_registry)。
        types:         state_schema.yaml 里 types: 段编译出的具名类型表,供
                        schemas/*.yaml 里的 !type 引用复用(见 state/schema.py)。
        stages_yaml:   stages.yaml 的路径,build_workflow/build_node_registry 时才编译
                        (编译需要 client_factory,不在 from_package 阶段做)。
        workflow_spec: workflow.yaml 解析出的原始 dict。
    """

    package: str
    root: Path
    state_schema: StateSchema
    types: dict[str, Any]
    stages_yaml: Path
    workflow_spec: dict[str, Any]

    @classmethod
    def from_package(cls, package: str) -> "Scenario":
        """按模块docstring的目录约定,装配 `package`(如 "scenarios.novel")这个场景包。"""
        module = importlib.import_module(package)
        root = Path(module.__file__).parent

        # 先导入 executors.py,触发 @executor/@node_wrapper 的登记副作用——stages.yaml
        # 编译时(build_workflow/build_node_registry)才会用到这些名字。
        _import_if_exists(f"{package}.executors")

        state_schema = StateSchema.from_yaml(root / "state_schema.yaml")
        types = load_types(root / "state_schema.yaml")
        schema_module.default_registry.register(state_schema)

        prompts_dir = root / "prompts"
        if prompts_dir.is_dir():
            prompt_module.load_dir(prompts_dir)

        schemas_dir = root / "schemas"
        if schemas_dir.is_dir():
            schema_module.default_registry.load_dir(schemas_dir, types=types)

        _load_toolsets(package, root)

        with (root / "workflow.yaml").open("r", encoding="utf-8") as f:
            workflow_spec = yaml.safe_load(f)

        return cls(
            package=package,
            root=root,
            state_schema=state_schema,
            types=types,
            stages_yaml=root / "stages.yaml",
            workflow_spec=workflow_spec,
        )

    def build_node_registry(
        self, client_factory: ClientFactory, stage_models: dict[str, str] | None = None
    ) -> NodeRegistry:
        """按 stages.yaml 组装本场景全部节点(见 engine.spec.build_node_registry)。"""
        return build_node_registry_from_spec(
            self.stages_yaml, client_factory=client_factory, stage_models=stage_models
        )

    def build_workflow(self, client_factory: ClientFactory) -> Workflow:
        """组装一个可运行的 Workflow:解析 model 继承 -> 建节点 -> 拼流程 -> 挂 state_schema。"""
        stage_models = Workflow.resolve_stage_models(self.workflow_spec)
        registry = self.build_node_registry(client_factory, stage_models)
        workflow = Workflow.from_spec(self.workflow_spec, registry)
        # from_spec 刻意只透传 spec 里的字符串引用(把它解析成具体 schema 不属于
        # 该方法职责),这里补上真正的 StateSchema 实例。
        workflow.state_schema = self.state_schema
        return workflow

    def empty_state(self) -> dict:
        """构造一份符合 schema 的空状态,作为一次新运行的起点。"""
        return self.state_schema.empty()


def _import_if_exists(module_name: str) -> None:
    """import 一个可选模块;只在它本身不存在时静默跳过,它内部的 import 错误照常抛出。"""
    try:
        importlib.import_module(module_name)
    except ModuleNotFoundError as err:
        if err.name != module_name:
            raise


def _load_toolsets(package: str, root: Path) -> None:
    """遍历 toolsets/ 子包的每个模块,自动登记模块顶层的 ToolSet 实例。"""
    if not (root / "toolsets").is_dir():
        return
    toolsets_pkg = importlib.import_module(f"{package}.toolsets")
    for _, name, _ in pkgutil.iter_modules(toolsets_pkg.__path__):
        module = importlib.import_module(f"{package}.toolsets.{name}")
        for value in vars(module).values():
            if isinstance(value, ToolSet):
                default_toolset_registry.register(value)

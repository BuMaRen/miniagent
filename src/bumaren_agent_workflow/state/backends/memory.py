"""InMemoryStateStore —— 进程内字典后端(适合测试与短流程)。

实现指导:
  - 内部用一个嵌套 dict 保存状态,path 以 "." 分割逐层寻址;
    数字段视为列表下标(如 "chapters.0.title")。
  - get:  逐层下钻,任一层缺失返回 default。
  - patch:定位到父节点后写入;若目标与新值均为 dict 做浅合并,否则覆盖;
          中间缺失的层按需创建。
  - append:定位到列表(缺失则建空列表)后 append。
  - slice: 对每个 path 调 get,组装 {path: value}。
  - snapshot/load: deepcopy 进出,保证与外部隔离。
可选:构造时传入 StateSchema,在 patch/append 前做 validate_path 校验。
"""

from __future__ import annotations

from typing import Any

from bumaren_agent_workflow.state.store import StateStore, StatePath
from bumaren_agent_workflow.state.schema import StateSchema

# 单独的哨兵对象,而不是 None:如果直接用 default(或 None)表示"没找到",
# 一旦 default 本身是 dict/list(比如 get(path, {})),中间层缺失时会把
# default 错误地当成"找到的节点"继续往下钻,可能钻出一个和 default 内容
# 有关但语义上完全无关的结果。_MISSING 保证"没找到"和"合法值恰好是 None"
# 这两种情况不会混淆。
_MISSING = object()


def _step(node: Any, level: str) -> Any:
    """在 node 上取路径的一段(只读,不做任何创建),取不到统一返回 _MISSING。

    digit 段永远按 list 下标解释,不会去 dict 里找同名字符串 key——
    这是本模块对"数字到底是下标还是 key"这个歧义的选择:强制数字只能是
    下标,dict 不允许用纯数字字符串当 key(校验交给 Schema 层做)。
    """
    if level.isdigit():
        index = int(level)
        if isinstance(node, list) and 0 <= index < len(node):
            return node[index]
        return _MISSING
    if isinstance(node, dict):
        return node.get(level, _MISSING)
    return _MISSING


def _merge(existing: Any, value: Any) -> Any:
    """patch 的合并策略:双方都是 dict 才浅合并(只覆盖 value 里出现的 key,
    existing 里没提到的 key 保留);只要有一边不是 dict(包括 existing
    因为路径不存在而是 _MISSING 的情况),新值整体替换旧值——不递归合并
    嵌套结构,想改深层字段要走更深的 path,而不是指望合并算法帮你猜。
    """
    if isinstance(existing, dict) and isinstance(value, dict):
        merged = dict(existing)
        merged.update(value)
        return merged
    return value


def _place(current: Any, level: str, child: Any) -> Any:
    """在 current 上按 level 创建一个原本不存在的中间层节点 child,返回 child。

    对 list 只允许"在末尾创建"(下标必须正好等于当前长度),中间跳跃越界
    直接报错,而不是自动拿空 dict/None 把空洞补齐——目的是让"path 写错了
    下标"这种输入错误在写入的当下就炸出来,而不是被悄悄接受,变成一份
    看似合法、实际有洞的状态,等到后面某个不相关的 Stage 读到才发现。
    """
    if level.isdigit():
        index = int(level)
        if not isinstance(current, list):
            raise TypeError(
                f"路径段 {level!r} 是数字下标,但父节点是 {type(current).__name__},不是 list"
            )
        if index != len(current):
            raise IndexError(
                f"list 长度为 {len(current)},只能在末尾(下标 {len(current)})创建新元素,不能在下标 {index} 处创建"
            )
        current.append(child)
    else:
        if not isinstance(current, dict):
            raise TypeError(
                f"路径段 {level!r} 是 key,但父节点是 {type(current).__name__},不是 dict"
            )
        current[level] = child
    return child


def _write_last(parent: Any, level: str, value: Any) -> None:
    """在已经定位好的父节点上写路径最后一段。

    和 _place 的区别:_place 只负责"创建一个全新的中间节点",_write_last
    负责"往一个已存在的字段写值",所以它对 dict 走 _merge(可能是合并而
    不是新建),对 list 既支持"替换已有下标"也支持"末尾追加"(等价于对
    最后一段单独重复一次 _place 的边界规则),但同样不允许越界跳跃创建。
    """
    if level.isdigit():
        index = int(level)
        if not isinstance(parent, list):
            raise TypeError(
                f"路径末段 {level!r} 是数字下标,但父节点是 {type(parent).__name__},不是 list"
            )
        if index == len(parent):
            parent.append(value)
        elif 0 <= index < len(parent):
            parent[index] = _merge(parent[index], value)
        else:
            raise IndexError(
                f"list 长度为 {len(parent)},下标 {index} 越界(只能替换已存在下标,或在末尾 {len(parent)} 处追加)"
            )
    else:
        if not isinstance(parent, dict):
            raise TypeError(
                f"路径末段 {level!r} 是 key,但父节点是 {type(parent).__name__},不是 dict"
            )
        parent[level] = _merge(parent.get(level, _MISSING), value)


def _locate_parent(root: dict, levels: list[str]) -> Any:
    """沿着 levels[:-1] 逐层下钻,找到(或按需创建)最后一段要写入的父节点。

    这里最关键的一步是"缺失的中间层该建 list 还是 dict":光看当前这一段
    本身(比如 "chapters")看不出答案,要看**下一段**是不是数字——
    "chapters" 后面接的是 "0" 这种数字段,说明 chapters 该是 list;
    后面接的是 "title" 这种 key,说明当前层该是 dict。所以这里故意传入
    完整的 levels(而不是只传 levels[:-1]),用 range(len(levels) - 1)
    控制只遍历到倒数第二段,但每一步都能安全地用 levels[i + 1] 向后看
    一格,包括看到最后一段本身。
    """
    current = root
    for i in range(len(levels) - 1):
        level = levels[i]
        child = _step(current, level)
        if child is _MISSING:
            child = [] if levels[i + 1].isdigit() else {}
            current = _place(current, level, child)
        else:
            current = child
    return current


def _get_or_create_list(parent: Any, level: str) -> list:
    """append 专用:取 parent[level] 当目标列表,不存在就新建一个空列表再返回。

    "不存在就建空列表"和 patch 的越界策略不矛盾:这里 level 是"字段名/
    下标本身"还没创建过,走的是 _place 的"新建"逻辑(同样受"只能在末尾建"
    的边界限制);如果这个字段已经存在但不是 list(比如是个字符串),
    说明调用方地址写错了,直接报错,不会把已有数据强行拗成 list。
    """
    target = _step(parent, level)
    if target is _MISSING:
        target = []
        _place(parent, level, target)
    if not isinstance(target, list):
        raise TypeError(
            f"路径末段 {level!r} 对应的字段不是 list,是 {type(target).__name__},不能 append"
        )
    return target


class InMemoryStateStore(StateStore):
    def __init__(
        self, schema: StateSchema | None = None, initial: dict[str, Any] | None = None
    ) -> None:
        self._schema = schema
        self._data: dict[str, Any] = initial or {}

    def get(self, path: StatePath, default: Any = None) -> Any:
        # 纯只读下钻,任何一段 _step 不到就短路返回 default——不创建任何
        # 缺失的中间层,这一点和 patch/append 是不对称的:读不该有副作用。
        current = self._data
        for level in path.split("."):
            current = _step(current, level)
            if current is _MISSING:
                return default
        return current

    def patch(self, path: StatePath, value: Any) -> None:
        if self._schema is not None:
            self._schema.validate_path(path, value)

        # 两步走:先定位/创建到"最后一段的父节点"(_locate_parent),
        # 再对最后一段做 merge-or-replace/append(_write_last)。
        # 拆成两步是因为"父节点该建成什么"和"最后一段该怎么写"是两条
        # 不同的规则(前者只有"建 list 还是 dict"一个选择,后者还要处理
        # 合并语义),硬合在一个循环里会更难读。
        levels = path.split(".")
        parent = _locate_parent(self._data, levels)
        _write_last(parent, levels[-1], value)

    def append(self, path: StatePath, value: Any) -> None:
        if self._schema is not None:
            self._schema.validate_path(path, value)

        # 复用和 patch 完全相同的"定位父节点"逻辑,区别只在最后一步:
        # patch 是"写/合并这个字段的值",append 是"这个字段必须是 list,
        # 取到(或新建)它之后往里塞一个元素",两者对"中间层怎么补"的规则
        # 是一致的,所以共享 _locate_parent 而不是各写一遍。
        levels = path.split(".")
        parent = _locate_parent(self._data, levels)
        target = _get_or_create_list(parent, levels[-1])
        target.append(value)

    def slice(self, paths: list[StatePath]) -> dict[str, Any]:
        return {path: self.get(path) for path in paths}

    def snapshot(self) -> dict[str, Any]:
        return deepcopy(self._data)

    def load(self, data: dict[str, Any]) -> None:
        self._data = deepcopy(data)


def deepcopy(obj: Any) -> Any:
    if isinstance(obj, dict):
        result = {}
        for k, v in obj.items():
            result[k] = deepcopy(v)
        return result
    elif isinstance(obj, list):
        return [deepcopy(v) for v in obj]
    elif isinstance(obj, set):
        raise NotImplementedError("deepcopy for set is not implemented")
    else:
        return obj

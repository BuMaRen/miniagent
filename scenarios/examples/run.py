"""统一入口:一次性跑完本目录下全部示例,或用 --example 只跑一个。

用法:
    python -m scenarios.examples.run                  # 全部跑一遍
    python -m scenarios.examples.run --example loop    # 只跑 Loop("continue")示例
    python -m scenarios.examples.run --list            # 列出可选的示例名
"""

from __future__ import annotations

import argparse

from scenarios.examples import (
    breaker_example,
    checkpoint_example,
    combined_example,
    foreach_example,
    loop_example,
    sequence_example,
    state_schema,
)

EXAMPLES = {
    "state_schema": ("数据声明(State Schema)", state_schema.__name__),
    "sequence": ("Sequence —— 顺序", sequence_example.main),
    "loop": ("Loop —— \"continue\"", loop_example.__name__),
    "foreach": ("ForEach —— 遍历", foreach_example.main),
    "breaker": ("Breaker —— \"break\"", breaker_example.main),
    "checkpoint": ("Checkpoint —— 人工断点(+ continue 组合)", checkpoint_example.__name__),
    "combined": ("组合:continue + break 同框", combined_example.main),
}

# 上面这张表里,大部分示例的"跑一遍"就是调用它的 main();但 state_schema.py /
# loop_example.py / checkpoint_example.py 在模块顶层用 `if __name__ == "__main__"`
# 直接跑了好几段演示、没有单独抽出一个 main() 函数(它们本身被设计成"能单独
# python -m 运行"的脚本),这里统一用 runpy 以脚本方式重新执行一遍,行为等价。
_MODULE_RUNNERS = {
    "state_schema": "scenarios.examples.state_schema",
    "loop": "scenarios.examples.loop_example",
    "checkpoint": "scenarios.examples.checkpoint_example",
}


def _run_one(name: str) -> None:
    title, target = EXAMPLES[name]
    print(f"\n{'=' * 70}\n{name}: {title}\n{'=' * 70}")
    if name in _MODULE_RUNNERS:
        import runpy

        runpy.run_module(_MODULE_RUNNERS[name], run_name="__main__")
    else:
        target()


def main() -> None:
    parser = argparse.ArgumentParser(description="跑一遍 scenarios/examples 下的原语示例")
    parser.add_argument("--example", choices=sorted(EXAMPLES), default=None, help="只跑指定的示例;不传则全部跑一遍")
    parser.add_argument("--list", action="store_true", help="列出可选的示例名后退出")
    args = parser.parse_args()

    if args.list:
        for name, (title, _) in EXAMPLES.items():
            print(f"  {name:<12} {title}")
        return

    names = [args.example] if args.example else list(EXAMPLES)
    for name in names:
        _run_one(name)


if __name__ == "__main__":
    main()

"""
简化的代码审查示例（不依赖 LLM）。

直接调用分析工具，展示代码审查功能的基本流程。

用法：
    python test_code_reviewer.py
"""

import os
import sys
import io

# 修复 Windows 控制台编码问题
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from skills.code_analysis_tools import (
    analyze_code_complexity,
    check_security_issues,
    check_code_style,
    generate_review_report
)


def test_review_file(file_path: str):
    """
    测试审查指定文件（不使用 LLM，直接调用工具）。
    """
    print(f"📝 开始审查文件: {file_path}\n")

    # 1. 读取文件
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            code = f.read()
        print(f"✅ 文件读取成功，共 {len(code.splitlines())} 行\n")
    except Exception as e:
        print(f"❌ 读取文件失败: {e}")
        return

    # 2. 分析复杂度
    print("🔍 分析代码复杂度...")
    complexity_result = analyze_code_complexity(code)
    print(complexity_result)
    print()

    # 3. 检查安全问题
    print("🔒 检查安全问题...")
    security_result = check_security_issues(code)
    print(security_result)
    print()

    # 4. 检查代码风格
    print("✨ 检查代码风格...")
    style_result = check_code_style(code)
    print(style_result)
    print()

    # 5. 生成报告
    print("📊 生成审查报告...")
    report = generate_review_report(
        file_path,
        complexity_result,
        security_result,
        style_result
    )
    print(report)
    print()

    # 6. 保存报告
    report_path = file_path.replace(".py", "_review_report.md")
    try:
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"💾 报告已保存到: {report_path}")
    except Exception as e:
        print(f"⚠️  保存报告失败: {e}")


def main():
    print("=" * 60)
    print("   Code Reviewer Skill - 测试示例")
    print("=" * 60)
    print()

    # 测试文件列表
    test_files = [
        "core/loop.py",
        "tools/schema.py",
        "debug_loop.py"
    ]

    for file_path in test_files:
        if os.path.exists(file_path):
            test_review_file(file_path)
            print("=" * 60)
            print()
            break  # 只测试第一个存在的文件
        else:
            print(f"⏭️  跳过不存在的文件: {file_path}")

    print("✅ 测试完成！")


if __name__ == "__main__":
    main()

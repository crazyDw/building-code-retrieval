#!/usr/bin/env python3
"""校验各目录的 README 是否登记了同目录下的所有 .md 文件。

约定见 docs/README.md：文件级索引写在各自目录的 README。
本脚本用来发现"文件加了、索引忘了更新"——仓库没有 CI，只能手动跑。

判定方式（故意放松）：README 里出现文件名（如 `naming.md`）或去掉扩展名的名字
（如 `naming`）即视为已登记；两者都没有才报遗漏。

用法:
    python -X utf8 scripts/check_readme_index.py          # 从仓库根递归扫描
    python -X utf8 scripts/check_readme_index.py docs     # 只扫指定目录

退出码: 0 全部已登记 / 1 存在遗漏。
"""
import os
import sys

SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", ".mypy_cache", ".ruff_cache"}


def read_text(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def display(path):
    """相对当前目录显示；跨盘符时退回绝对路径（Windows 上 relpath 会抛 ValueError）。"""
    try:
        return os.path.relpath(path)
    except ValueError:
        return os.path.abspath(path)


def check_dir(path):
    """目录有 README 时返回 (README 相对路径, 未登记的 .md 列表)，否则返回 None。"""
    readme = os.path.join(path, "README.md")
    if not os.path.isfile(readme):
        return None
    text = read_text(readme)
    missing = []
    for name in sorted(os.listdir(path)):
        if not name.endswith(".md") or name == "README.md":
            continue
        if not os.path.isfile(os.path.join(path, name)):
            continue
        if name not in text and name[:-3] not in text:
            missing.append(name)
    return display(readme), missing


def walk(targets):
    for target in targets:
        if os.path.isfile(target):
            continue
        for root, dirs, _ in os.walk(target):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            result = check_dir(root)
            if result:
                yield result


def main(argv):
    targets = [a for a in argv[1:] if not a.startswith("--")] or ["."]
    checked = 0
    problems = 0
    for readme, missing in sorted(walk(targets), key=lambda item: item[0]):
        checked += 1
        if missing:
            problems += len(missing)
            print(f"!! {readme} 未登记: {'、'.join(missing)}")
    print("=" * 60)
    print(f"检查 {checked} 个 README，未登记 {problems} 个文件")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

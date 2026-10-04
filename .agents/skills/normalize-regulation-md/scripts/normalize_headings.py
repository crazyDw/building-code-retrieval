#!/usr/bin/env python3
"""规范化规范 Markdown 的标题标记。

目标形态：章 `#`、节 `##`、前言与目次 `#`、目次条目无标记、条文无标记。

用法:
    python normalize_headings.py <目录或文件> [...]            # 试运行，只打印计划
    python normalize_headings.py <目录或文件> [...] --apply     # 写入

只改行首标记，行内其余字符与行尾空格原样保留；沿用原文件的编码与行尾分隔符。
逐行断言，任一行不符合预期即整体中止该文件，不部分写入。
"""
import os
import re
import sys

HEAD = re.compile(r'^(#{1,6})\s+(.*)$')
CLS = re.compile(r'^(\d+)\.(\d+)\.(\d+)(?:\s|$)')
SEC = re.compile(r'^(\d+)\.(\d+)(?:\s|$)')
CHAP = re.compile(r'^(\d+)(?:\s|$)')
PAGENO = re.compile(r'\s\d+\s*$')


def toc_range(lines):
    """返回 (目次标题行号, 正文起始行号)；无目次时返回 (None, 0)。"""
    toc = None
    for i, line in enumerate(lines):
        m = HEAD.match(line)
        if m and re.match(r'^目\s*次\s*$', m.group(2).strip()):
            toc = i
            break
    if toc is None:
        return None, 0
    for i in range(toc + 1, len(lines)):
        text = re.sub(r'^#{1,6}\s*', '', lines[i].strip())
        if not text or PAGENO.search(text):
            continue
        if CHAP.match(text) or SEC.match(text):
            return toc, i
    return toc, toc + 1


def iter_files(targets):
    for target in targets:
        if os.path.isdir(target):
            for root, _, names in os.walk(target):
                for name in sorted(names):
                    if name.endswith(".md"):
                        yield os.path.join(root, name)
        elif target.endswith(".md"):
            yield target


def build_plan(lines):
    """返回 [(行号, 动作, 原行, 原因)]。动作: dehead / h1 / h2。"""
    toc, body = toc_range(lines)
    plan = []
    for i, line in enumerate(lines):
        m = HEAD.match(line)
        if not m:
            continue
        text, hashes = m.group(2).strip(), m.group(1)
        if toc is not None and toc < i < body:
            plan.append((i + 1, "dehead", line, "目次条目去掉标记"))
            continue
        if CLS.match(text):
            plan.append((i + 1, "dehead", line, "条文被误标为标题，还原为条文"))
        elif SEC.match(text):
            if hashes != "##":
                plan.append((i + 1, "h2", line, "节应为 ##"))
        elif CHAP.match(text):
            if hashes != "#":
                plan.append((i + 1, "h1", line, "章应为 #"))
        elif hashes != "#":
            plan.append((i + 1, "h1", line, "前言/目次应为 #"))
    return plan


def rewrite(line, action):
    m = HEAD.match(line)
    if not m:
        raise AssertionError("不是标题行")
    if action == "dehead":
        return m.group(2)
    if action == "h1":
        return "# " + m.group(2)
    if action == "h2":
        return "## " + m.group(2)
    raise AssertionError("未知动作 %s" % action)


def main(argv):
    targets = [a for a in argv[1:] if not a.startswith("--")] or ["数据库上传资料"]
    apply = "--apply" in argv

    changed_files = total_lines = 0
    for path in iter_files(targets):
        raw = open(path, encoding="utf-8", newline="").read()
        sep = "\r\n" if "\r\n" in raw else "\n"
        lines = raw.split(sep)
        plan = build_plan(lines)
        print("=" * 62)
        print("%s   待改 %d 行" % (os.path.basename(path), len(plan)))
        if not plan:
            continue
        for ln, action, line, why in plan:
            print("  L%-5d %s" % (ln, why))
            print("        %s" % line[:60])
            print("     -> %s" % rewrite(line, action)[:60])
        if apply:
            try:
                newlines = list(lines)
                for ln, action, _, _ in plan:
                    newlines[ln - 1] = rewrite(lines[ln - 1], action)
            except AssertionError as exc:
                print("  !! 断言失败（%s），该文件未写入" % exc)
                continue
            open(path, "w", encoding="utf-8", newline="").write(sep.join(newlines))
            print("  已写入 %d 行" % len(plan))
        changed_files += 1
        total_lines += len(plan)

    print("=" * 62)
    print("%s：%d 个文件、%d 行"
          % ("已应用" if apply else "试运行（未写入，加 --apply 落盘）",
             changed_files, total_lines))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

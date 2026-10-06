#!/usr/bin/env python3
"""只读普查规范 Markdown 的层级结构。

用法:
    python scan_structure.py <目录或文件> [...]

输出每个文件的章/节/条/款/项数量、标记异常清单、条号缺口。不做任何写入。
退出码: 0 全部正常 / 2 存在异常或缺口 / 1 未找到文件。
"""
import os
import re
import sys

HEAD = re.compile(r'^(#{1,6})\s+(.*)$')
CLS = re.compile(r'^(\d+)\.(\d+)\.(\d+)(?:\s|$)', re.M)
SEC = re.compile(r'^(\d+)\.(\d+)(?:\s|$)')
CHAP = re.compile(r'^(\d+)(?:\s|$)')
PAGENO = re.compile(r'\s\d+\s*$')
KUAN = re.compile(r'^\d+\s+\S')
XIANG = re.compile(r'^\d+[）)]')


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


def report(path):
    with open(path, encoding="utf-8") as handle:
        raw = handle.read()
    lines = raw.split("\n")
    toc, body = toc_range(lines)
    ch = se = ku = xi = 0
    issues = []
    for i, line in enumerate(lines):
        m = HEAD.match(line)
        if m:
            text, hashes = m.group(2).strip(), m.group(1)
            if toc is not None and toc < i < body:
                issues.append((i + 1, "目次条目带标题标记", line[:48]))
                continue
            if CLS.match(text):
                issues.append((i + 1, "条文被标为标题", line[:48]))
            elif SEC.match(text):
                se += 1
                if hashes != "##":
                    issues.append((i + 1, "节标记应为 ##", line[:48]))
            elif CHAP.match(text):
                ch += 1
                if hashes != "#":
                    issues.append((i + 1, "章标记应为 #", line[:48]))
            elif hashes != "#":
                issues.append((i + 1, "前置标记应为 #", line[:48]))
            continue
        if i > body and not line.startswith(" "):
            if KUAN.match(line):
                ku += 1
            elif XIANG.match(line):
                xi += 1

    nums = [(int(a), int(b), int(c)) for a, b, c in CLS.findall(raw)]
    gaps = []
    for k in range(1, len(nums)):
        a, b, c = nums[k - 1]
        A, B, C = nums[k]
        if (a, b) == (A, B):
            ok = c + 1 == C
        elif a == A and b + 1 == B:
            ok = C == 1
        else:
            ok = a + 1 == A and C == 1
        if not ok:
            gaps.append(f"{a}.{b}.{c}->{A}.{B}.{C}")

    return dict(
        ch=ch, se=se, cl=len(nums), ku=ku, xi=xi, issues=issues, gaps=gaps, body=body + 1
    )


def main(argv):
    targets = [a for a in argv[1:] if not a.startswith("--")] or ["数据库上传资料"]
    total = dict(ch=0, se=0, cl=0, ku=0, xi=0, issues=0, gaps=0)
    found = False
    for path in iter_files(targets):
        found = True
        r = report(path)
        print("=" * 62)
        print(f"{os.path.basename(path)}   (正文起始 行{r['body']})")
        print(
            f"  章 {r['ch']}  节 {r['se']}  条 {r['cl']}  款 {r['ku']}  项 {r['xi']}"
            f"    标记异常 {len(r['issues'])}  条号缺口 {len(r['gaps'])}"
        )
        for ln, kind, text in r["issues"]:
            print(f"    !! L{ln:<5d} {kind}: {text}")
        for g in r["gaps"]:
            print(f"    !! 条号缺口 {g}")
        for k in ("ch", "se", "cl", "ku", "xi"):
            total[k] += r[k]
        total["issues"] += len(r["issues"])
        total["gaps"] += len(r["gaps"])
    if not found:
        print(f"未找到 .md 文件：{', '.join(targets)}")
        return 1
    print("=" * 62)
    print(
        f"合计  章 {total['ch']}  节 {total['se']}  条 {total['cl']}  款 {total['ku']}"
        f"  项 {total['xi']}    标记异常 {total['issues']}  条号缺口 {total['gaps']}"
    )
    return 0 if total["issues"] == 0 and total["gaps"] == 0 else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))

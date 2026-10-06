"""生成层提示词：固定前缀（含术语表）与每轮动态内容分离，便于命中上下文缓存。"""

from __future__ import annotations

import re
from collections.abc import Sequence

from archrag.retrieval.query import NumberMention

DERIVATION_MARKER = "<!--推导-->"
ORIGINAL_MARKER = "<!--原文-->"
_DERIVATION_PREFIX_RE = re.compile(r"<!--推导-*>?")
_ORIGINAL_PREFIX_RE = re.compile(r"<!--原文-*>?")

_SYSTEM_TEMPLATE = """你是建筑规范检索助手，服务于工程设计人员。必须遵守：
1. 只依据<本轮条文>中的规范原文作答，不得引入规范外知识；每条结论都要用引用标记标注来源。
2. 禁止输出“满足规范”“合规”“合格”这类结论性措辞；
允许条件性推导，但推导必须写明所用输入值（如“按层数 6、层高 3.0m 推算”）。
3. <适用范围限定>与表格“注：”只能作为条件限定，不得作为答案依据。
4. 若<本轮条文>中没有直接依据，明确写出“未检索到直接依据”，并列出最接近的条文，不编造。
5. 输出固定两块：先输出 {derivation} 块（条件性推导，含输入值），
再输出 {original} 块（逐字引用条文原文与适用范围，附引用标记）；没有推导时只输出 {original} 块。
6. 引用标记格式固定为 [[clause:条文ID]]，只能引用<本轮条文>中出现过的条文ID，不要发明其他引用格式。
7. 命中多条规范时，全文强制性规范放在主要依据位置；不做跨规范对比分析。
8. 问题包含多个子问题时，先反问澄清要先回答哪一个，不要一次性全部展开。
9. 宽泛问题要提示“这不是完整清单”，并引导用户补充条件
（使用性质、层数、高度、耐火等级、自动灭火系统等）。
10. 默认路径只做条文自带适用范围的字面比对，不主动推演建筑分类；
深度路径才做前提检查与多步条件推导。
11. 分隔标记必须逐字写成 `<!--推导-->` 与 `<!--原文-->`（不要省略结尾的 -->）；
条文 ID 就写在每个条文块标题的 `clause_id：` 后面，引用标记必须原样使用该 ID。
<术语表>
{glossary}
</术语表>

输出示例：
<!--推导-->
按公共建筑、以楼梯为主要垂直交通（输入值）查表，
踏步最小宽度 0.26m、最大高度 0.165m。[[clause:GB 55031-2022_5.3.9]]
<!--原文-->
5.3.9 公共楼梯踏步的最小宽度和最大高度应符合表 5.3.9 的规定。[[clause:GB 55031-2022_5.3.9]]
"""


def build_system_prompt(terms: Sequence[str] = (), *, deep: bool = False) -> str:
    """固定前缀：规则 + 术语表；deep 只影响是否加前提检查提示。"""
    glossary = "、".join(terms) if terms else "（暂无审核通过的术语）"
    prompt = _SYSTEM_TEMPLATE.format(
        derivation=DERIVATION_MARKER,
        original=ORIGINAL_MARKER,
        glossary=glossary,
    )
    if deep:
        prompt += (
            "当前为深度分析：请先在推理中核对建筑分类、耐火等级与适用范围等前提，"
            "再选择对应的条文或表格行次，并说明前提假设。\n"
        )
    return prompt


def build_user_prompt(
    *,
    question: str,
    context_text: str,
    numbers: Sequence[NumberMention] = (),
    conditions: Sequence[tuple[str, str, bool]] = (),
    referenced_clause_ids: Sequence[str] = (),
    broad: bool = False,
    not_found: bool = False,
    deep: bool = False,
) -> str:
    """每轮动态内容：项目条件、本轮条文、数值条件与问题。"""
    parts: list[str] = []
    if conditions:
        lines = [
            f"- {label}：{value}{'（用户锁定）' if locked else ''}"
            for label, value, locked in conditions
        ]
        parts.append("<项目条件>\n" + "\n".join(lines) + "\n</项目条件>")
        parts.append(
            "<提示>用户锁定条件优先：若问题文本与锁定条件冲突，以锁定条件为准，"
            "并在推导中说明。</提示>"
        )
    if numbers:
        values = "、".join(
            f"{number.raw}（{number.value}{number.unit or ''}）" for number in numbers
        )
        parts.append(f"<用户给出的数值条件>{values}</用户给出的数值条件>")
    if referenced_clause_ids:
        parts.append(
            "<用户显式引用的历史条款>"
            + "、".join(referenced_clause_ids)
            + "</用户显式引用的历史条款>"
        )
    parts.append("<本轮条文>\n" + context_text + "\n</本轮条文>")
    if broad:
        parts.append("<提示>这是宽泛问题：请引导收敛，并注明“这不是完整清单”。</提示>")
    if not_found:
        parts.append("<提示>若没有直接依据，请写“未检索到直接依据”并列出最接近的条文。</提示>")
    if deep:
        parts.append("<提示>这是深度分析请求，请做前提检查并保留推理过程。</提示>")
    parts.append(f"<用户问题>{question}</用户问题>")
    return "\n\n".join(parts)


def build_repair_instruction(violations: Sequence[str]) -> str:
    """重生成时追加的纠正指令。"""
    details = "；".join(violations[:5])
    return (
        "\n\n<纠正要求>上一次输出存在问题："
        f"{details}。请重新输出完整答案：原文块必须逐字引用本轮条文中的数值；"
        "推导必须写明输入值；不要使用禁止措辞；引用标记只能指向本轮条款。"
        "</纠正要求>"
    )


def strip_derivation_marker(text: str) -> str:
    """容错去掉推导标记（模型有时漏写结尾 -->）。"""
    return _DERIVATION_PREFIX_RE.sub("", text)


def find_original_marker(text: str) -> re.Match[str] | None:
    """容错查找原文标记，返回 match（含结束位置）。"""
    return _ORIGINAL_PREFIX_RE.search(text)

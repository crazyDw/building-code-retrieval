"""术语候选、别名种子与随机核对清单测试。"""

from __future__ import annotations

import json
from pathlib import Path

from archrag.corpus.checklist import build_checklist, write_checklist
from archrag.corpus.lexicon import build_candidates, write_candidates


def test_lexicon_candidates_on_real_corpus(parsed_corpus) -> None:
    candidates = build_candidates(list(parsed_corpus.values()))
    terms = {item.term: item for item in candidates.terms}
    assert "混凝土" in terms
    assert terms["混凝土"].freq >= 50
    assert len(candidates.terms) <= 500
    assert all(item.freq > 0 and item.score > 0 for item in candidates.terms)


def test_alias_seeds_cover_standard_id_name_and_short_name(parsed_corpus) -> None:
    candidates = build_candidates(list(parsed_corpus.values()))
    aliases = {(item.standard_id, item.alias_type, item.alias) for item in candidates.aliases}
    assert ("GB 55031-2022", "standard_id", "GB 55031-2022") in aliases
    assert ("GB 55031-2022", "full_name", "民用建筑通用规范") in aliases
    assert ("GB 55031-2022", "short_name", "民用建筑") in aliases
    assert ("GB 55038-2025", "short_name", "住宅") in aliases


def test_symbol_expansions_are_produced(parsed_corpus) -> None:
    candidates = build_candidates(list(parsed_corpus.values()))
    expansions = {(item.from_text, item.to_text) for item in candidates.expansions}
    assert ("Eh,av", "平均水平照度") in expansions
    assert ("Ra", "一般显色指数") in expansions


def test_write_candidates_json(tmp_path: Path, parsed_corpus) -> None:
    path = write_candidates(
        build_candidates(list(parsed_corpus.values())), tmp_path / "lexicon.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert set(payload) == {"terms", "aliases", "expansions"}
    assert payload["terms"] and payload["aliases"] and payload["expansions"]


def test_checklist_is_reproducible_and_has_50_items(tmp_path: Path, parsed_corpus) -> None:
    for parsed in parsed_corpus.values():
        items = build_checklist(parsed, size=50, seed="fixed")
        assert len(items) == 50
        assert len({item.clause_id for item in items}) == 50
        assert build_checklist(parsed, size=50, seed="fixed") == items
        path = write_checklist(parsed, tmp_path, size=50, seed="fixed")
        assert path.read_text(encoding="utf-8").count("## ") == 50

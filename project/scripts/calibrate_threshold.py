#!/usr/bin/env python3
"""阈值标定：读评测的正负样本重排分，产出曲线并按需回填 .env。"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from archrag.config import REPO_ROOT


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="标定 SCORE_THRESHOLD")
    parser.add_argument("--eval-file", required=True, help="eval_*.json 明细文件")
    parser.add_argument(
        "--output",
        default=str(REPO_ROOT / "data" / "eval" / "threshold_curve.json"),
    )
    parser.add_argument("--apply", action="store_true", help="回填 .env 的 SCORE_THRESHOLD")
    parser.add_argument(
        "--negatives-file",
        default="",
        help="超范围负样本 JSON（eval_retrieval.py --only-negatives 产物）",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="显式运营阈值（不给则用 Youden 最优值）",
    )
    args = parser.parse_args(argv)

    results = json.loads(Path(args.eval_file).read_text(encoding="utf-8"))
    # 每道题取「金标最高分」与「最难负样本最高分」，避免同题 24 个负样本造成失衡。
    positives = [
        max(item["positives"])
        for item in results
        if item.get("positives")
    ]
    if args.negatives_file:
        payload = json.loads(Path(args.negatives_file).read_text(encoding="utf-8"))
        negatives = [
            float(item["top_score"])
            for item in payload
            if item.get("top_score") is not None
        ]
    else:
        negatives = [
            max(item["negatives"])
            for item in results
            if item.get("positives") and item.get("negatives")
        ]
    if not positives or not negatives:
        print("正负样本不足，无法标定")
        return 2
    low = min(min(positives), min(negatives))
    high = max(max(positives), max(negatives))
    steps = 200
    curve = []
    best = {"threshold": 0.0, "youden": -1.0}
    for step in range(steps + 1):
        threshold = low + (high - low) * step / steps
        tpr = sum(score >= threshold for score in positives) / len(positives)
        fpr = sum(score >= threshold for score in negatives) / len(negatives)
        youden = tpr - fpr
        curve.append(
            {"threshold": round(threshold, 4), "tpr": round(tpr, 4), "fpr": round(fpr, 4)}
        )
        if youden > best["youden"]:
            best = {"threshold": round(threshold, 4), "youden": round(youden, 4)}
    payload = {
        "positives": len(positives),
        "negatives": len(negatives),
        "positive_mean": round(sum(positives) / len(positives), 4),
        "negative_mean": round(sum(negatives) / len(negatives), 4),
        "best": best,
        "curve": curve,
    }
    chosen = best["threshold"] if args.threshold is None else round(args.threshold, 4)
    payload["operational_threshold"] = chosen
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(
        f"正样本 {len(positives)}（均值 {payload['positive_mean']}）/ "
        f"负样本 {len(negatives)}（均值 {payload['negative_mean']}）"
    )
    print(f"Youden 最优 {best['threshold']}；采用阈值 {chosen} → {output}")
    if args.apply:
        _apply_threshold(chosen)
    return 0


def _apply_threshold(threshold: float) -> None:
    env_path = REPO_ROOT / ".env"
    if not env_path.is_file():
        print("!! .env 不存在，未回填")
        return
    text = env_path.read_text(encoding="utf-8")
    updated, count = re.subn(
        r"(?m)^SCORE_THRESHOLD=.*$",
        f"SCORE_THRESHOLD={threshold}",
        text,
    )
    if count == 0:
        print("!! .env 中没有 SCORE_THRESHOLD 键，未回填")
        return
    env_path.write_text(updated, encoding="utf-8")
    print(f"已回填 .env：SCORE_THRESHOLD={threshold}")


if __name__ == "__main__":
    sys.exit(main())

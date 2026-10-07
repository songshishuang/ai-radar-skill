#!/usr/bin/env python3
"""ai-radar 评分校准：用人工标注的金标样本对照宿主 agent 的打分，算查准 / 查全（纯标准库，只读）。

金标（JSONL）每行一条：
  {"caseId": "...", "material": {"title", "source", "tier", "published_at", "summary"},
   "split": "dev|holdout", "stratum": "...", "gold": {"bucket": "must|notable|skip|either"}}
预测（JSONL）每行一条——宿主 agent 按 references/lenses.md、只看 material 打分后写出：
  {"caseId": "...", "importance": 8}      或      {"caseId": "...", "bucket": "must"}

用法:
  python gold_eval.py --gold tests/gold/seed.jsonl --pred preds.jsonl --split dev
  python gold_eval.py --gold ... --pred ... --must 8 --notable 6 --json

分档：importance ≥ --must（默认 8）为 must；≥ --notable（默认 6）为 notable；其余为 skip。
gold 为 either 的条目不计入准确率；缺预测的条目一律算判错。流程见 references/lenses.md「校准」。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

CLASSES = ("must", "notable", "skip")


def load_jsonl(path) -> list:
    rows = []
    for ln, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except ValueError as e:
                raise ValueError(f"{path} 第 {ln} 行不是合法 JSON：{e}") from e
    return rows


def bucket_of(pred: dict | None, must: int, notable: int) -> str | None:
    if not pred:
        return None
    if pred.get("bucket") in CLASSES:
        return pred["bucket"]
    score = pred.get("importance")
    if not isinstance(score, (int, float)):
        return None
    return "must" if score >= must else "notable" if score >= notable else "skip"


def evaluate(gold_rows: list, preds: list, split: str = "all", must: int = 8, notable: int = 6) -> dict:
    by_id = {p["caseId"]: p for p in preds if "caseId" in p}
    rows = [g for g in gold_rows if split == "all" or g.get("split") == split]
    scored = [g for g in rows if g["gold"]["bucket"] in CLASSES]
    confusion = {c: {p: 0 for p in CLASSES + ("missing",)} for c in CLASSES}
    mismatches, correct = [], 0
    for g in scored:
        gold = g["gold"]["bucket"]
        pred = by_id.get(g["caseId"])
        got = bucket_of(pred, must, notable)
        confusion[gold][got or "missing"] += 1
        if got == gold:
            correct += 1
        else:
            mismatches.append(
                {
                    "caseId": g["caseId"],
                    "title": g.get("material", {}).get("title"),
                    "stratum": g.get("stratum"),
                    "gold": gold,
                    "pred": got or "missing",
                    "importance": (pred or {}).get("importance"),
                }
            )

    per_class = {}
    for c in CLASSES:
        tp = confusion[c][c]
        fp = sum(confusion[o][c] for o in CLASSES if o != c)
        fn = sum(v for k, v in confusion[c].items() if k != c)
        p = tp / (tp + fp) if tp + fp else None
        r = tp / (tp + fn) if tp + fn else None
        f1 = (2 * p * r / (p + r) if p + r else 0.0) if p is not None and r is not None else None
        per_class[c] = {"precision": p, "recall": r, "f1": f1, "support": tp + fn}

    sweep = []
    numeric = [(g["gold"]["bucket"], by_id[g["caseId"]]["importance"]) for g in scored if isinstance(by_id.get(g["caseId"], {}).get("importance"), (int, float))]
    for th in range(6, 11):
        tp = sum(1 for gold, s in numeric if s >= th and gold == "must")
        fp = sum(1 for gold, s in numeric if s >= th and gold != "must")
        fn = sum(1 for gold, s in numeric if s < th and gold == "must")
        sweep.append({"must_threshold": th, "precision": tp / (tp + fp) if tp + fp else None, "recall": tp / (tp + fn) if tp + fn else None, "selected": tp + fp})

    return {
        "split": split,
        "thresholds": {"must": must, "notable": notable},
        "n_cases": len(rows),
        "n_scored": len(scored),
        "n_either": len(rows) - len(scored),
        "n_missing": sum(confusion[c]["missing"] for c in CLASSES),
        "accuracy": correct / len(scored) if scored else None,
        "per_class": per_class,
        "confusion": confusion,
        "must_sweep": sweep,
        "mismatches": mismatches,
    }


def _pct(x) -> str:
    return "  -  " if x is None else f"{x * 100:5.1f}%"


def format_report(m: dict) -> str:
    out = [
        f"金标评测（split={m['split']}，must≥{m['thresholds']['must']}，notable≥{m['thresholds']['notable']}）",
        f"样本 {m['n_cases']} 条：计分 {m['n_scored']}，两可 {m['n_either']}，缺预测 {m['n_missing']}",
        f"准确率：{_pct(m['accuracy'])}",
        "",
        "| 档位 | 查准 | 查全 | F1 | 样本 |",
        "|---|---|---|---|---|",
    ]
    for c in CLASSES:
        pc = m["per_class"][c]
        out.append(f"| {c} | {_pct(pc['precision'])} | {_pct(pc['recall'])} | {_pct(pc['f1'])} | {pc['support']} |")
    out += ["", "混淆矩阵（行 = 金标，列 = 预测）", "| 金标\\预测 | must | notable | skip | missing |", "|---|---|---|---|---|"]
    for c in CLASSES:
        row = m["confusion"][c]
        out.append(f"| {c} | {row['must']} | {row['notable']} | {row['skip']} | {row['missing']} |")
    out += ["", "必读门槛扫描（只算给了 importance 的预测）", "| 门槛 | 入选 | 查准 | 查全 |", "|---|---|---|---|"]
    for s in m["must_sweep"]:
        out.append(f"| ≥{s['must_threshold']} | {s['selected']} | {_pct(s['precision'])} | {_pct(s['recall'])} |")
    if m["mismatches"]:
        out += ["", f"判错 {len(m['mismatches'])} 条："]
        out += [f"  - {x['caseId']}（{x.get('stratum') or '-'}）金标 {x['gold']} → 预测 {x['pred']}（{x['importance']}）：{x['title']}" for x in m["mismatches"]]
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="ai-radar 评分校准（金标评测）")
    ap.add_argument("--gold", required=True, help="金标 JSONL")
    ap.add_argument("--pred", required=True, help="预测 JSONL")
    ap.add_argument("--split", default="all", help="dev / holdout / all（默认 all）")
    ap.add_argument("--must", type=int, default=8, help="必读门槛（默认 8）")
    ap.add_argument("--notable", type=int, default=6, help="值得关注门槛（默认 6）")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args(argv)
    try:
        metrics = evaluate(load_jsonl(args.gold), load_jsonl(args.pred), args.split, args.must, args.notable)
    except (OSError, ValueError, KeyError) as e:
        print(f"读取失败：{e}", file=sys.stderr)
        return 2
    print(json.dumps(metrics, ensure_ascii=False, indent=2) if args.json else format_report(metrics))
    return 0


if __name__ == "__main__":
    sys.exit(main())

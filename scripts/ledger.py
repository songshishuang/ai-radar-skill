#!/usr/bin/env python3
"""ai-radar 已报事件台账 / 周期汇编（纯标准库，只读）。

台账（默认）：列出最近 N 期日报里进过必读的事件。生成新一期前先读一遍——
已报事件只有出现「当事方新动作」或「≥4 家独立来源报道的新进展」才能再进必读，
否则进「🔁 续报」一行或不报（规则见 references/report-format.md）。
    python ledger.py --reports ./ai-radar-reports --issues 7

汇编（--compile）：把最近 N 天日报的条目合并去重、按日报给它的位置排序，
作为周报 / 月报的候选清单（周报取 20、月报取 30），缺日再用 fetch.py 补抓。
    python ledger.py --reports ./ai-radar-reports --compile --days 7 --top 20

优先读日报旁的结构化 JSON（verify_report.py --emit-json 产出），没有则直接解析 Markdown。
台账默认不含今天的日报（你正要生成它）；汇编的天数窗口包含今天。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_report import SCHEMA, normalize_url, parse_report  # noqa: E402

_DAILY_RE = re.compile(r"^daily-(\d{4}-\d{2}-\d{2})\.md$")
# 日报给条目的位置权重：头条 > 必读 > 值得关注 > 续报
_WEIGHTS = {"lead": 5.0, "must": 3.0, "notable": 1.0, "followups": 0.5}


def load_dailies(reports_dir, start: date | None = None, end: date | None = None) -> list:
    """读取日期落在 [start, end] 闭区间的日报，返回 [(date, report_dict)]，按日期升序。"""
    out = []
    for p in sorted(Path(reports_dir).glob("daily-*.md")):
        m = _DAILY_RE.match(p.name)
        if not m:
            continue
        d = date.fromisoformat(m.group(1))
        if (start and d < start) or (end and d > end):
            continue
        rep = None
        side = p.with_suffix(".json")
        if side.exists():
            try:
                data = json.loads(side.read_text(encoding="utf-8"))
                rep = data if data.get("schema") == SCHEMA else None
            except (OSError, ValueError):
                rep = None
        if rep is None:
            rep = parse_report(p.read_text(encoding="utf-8"), p.name)
        out.append((d, rep))
    return out


def reported_events(dailies: list) -> list:
    """台账：每期必读条目，按日期倒序。"""
    rows = []
    for d, rep in sorted(dailies, key=lambda x: x[0], reverse=True):
        for e in rep.get("must", []):
            rows.append(
                {
                    "date": d.isoformat(),
                    "rank": e.get("rank"),
                    "importance": e.get("importance"),
                    "coverage": e.get("coverage"),
                    "title": e["title"],
                    "url": e["url"],
                }
            )
    return rows


def _bigrams(s: str) -> set:
    s = re.sub(r"[\W_]+", "", s.lower())
    return {s[i : i + 2] for i in range(len(s) - 1)} if len(s) > 1 else {s}


def _similar(a: str, b: str, threshold: float = 0.6) -> bool:
    x, y = _bigrams(a), _bigrams(b)
    return len(x & y) / max(1, len(x | y)) >= threshold


def compile_candidates(dailies: list, top: int = 20) -> list:
    """汇编：同一事件（同链接或标题高度相似）跨天只算一件，按位置权重累加排序。"""
    groups = []
    for d, rep in dailies:
        for kind in ("must", "notable", "followups"):
            for e in rep.get(kind, []):
                pos = "lead" if kind == "must" and e.get("rank") == 1 else kind
                key = normalize_url(e["url"])
                g = next((g for g in groups if key in g["_urls"] or _similar(g["title"], e["title"])), None)
                if g is None:
                    g = {"title": e["title"], "url": e["url"], "best": pos, "score": 0.0, "days": set(), "max_importance": 0, "max_coverage": 0, "_urls": set()}
                    groups.append(g)
                g["_urls"].add(key)
                g["days"].add(d.isoformat())
                g["score"] += _WEIGHTS[pos]
                if _WEIGHTS[pos] > _WEIGHTS[g["best"]]:
                    g["best"], g["title"], g["url"] = pos, e["title"], e["url"]
                g["max_importance"] = max(g["max_importance"], e.get("importance") or 0)
                g["max_coverage"] = max(g["max_coverage"], e.get("coverage") or 0)
    for g in groups:
        g["days"] = sorted(g["days"])
        del g["_urls"]
    groups.sort(key=lambda g: (-g["score"], -g["max_importance"], -g["max_coverage"]))
    return groups[:top]


def _format_ledger(rows: list, n_issues: int) -> str:
    if not rows:
        return "已报事件台账：无（近期没有日报）"
    out = [f"已报事件台账（最近 {n_issues} 期必读，共 {len(rows)} 件）", "", "| 日期 | 位 | 分 | 源 | 事件 |", "|---|---|---|---|---|"]
    for r in rows:
        cov = r["coverage"] if r["coverage"] is not None else "-"
        out.append(f"| {r['date']} | {r['rank']} | {r['importance']} | {cov} | [{r['title']}]({r['url']}) |")
    return "\n".join(out)


def _format_candidates(groups: list, start: date, end: date) -> str:
    if not groups:
        return f"汇编候选：{start} ~ {end} 窗口内没有日报"
    label = {"lead": "头条", "must": "必读", "notable": "关注", "followups": "续报"}
    out = [f"汇编候选（{start} ~ {end}，共 {len(groups)} 件）", "", "| # | 得分 | 最高位置 | 天数 | 分 | 事件 |", "|---|---|---|---|---|---|"]
    for i, g in enumerate(groups, 1):
        out.append(f"| {i} | {g['score']:g} | {label[g['best']]} | {len(g['days'])} | {g['max_importance']} | [{g['title']}]({g['url']}) |")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="ai-radar 已报事件台账 / 周期汇编")
    ap.add_argument("--reports", default="./ai-radar-reports", help="报告目录")
    ap.add_argument("--today", default=None, help="基准日期 YYYY-MM-DD（默认今天）")
    ap.add_argument("--issues", type=int, default=7, help="台账：回看最近几期日报（默认 7）")
    ap.add_argument("--include-today", action="store_true", help="台账：把今天已有的日报也算进去")
    ap.add_argument("--compile", action="store_true", help="汇编模式：生成周报 / 月报候选清单")
    ap.add_argument("--days", type=int, default=7, help="汇编：回看天数，含今天（周报 7、月报 30）")
    ap.add_argument("--top", type=int, default=20, help="汇编：取前几件（周报 20、月报 30）")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args(argv)

    today = date.fromisoformat(args.today) if args.today else date.today()
    if args.compile:
        start = today - timedelta(days=args.days - 1)
        groups = compile_candidates(load_dailies(args.reports, start, today), args.top)
        print(json.dumps(groups, ensure_ascii=False, indent=2) if args.json else _format_candidates(groups, start, today))
        return 0

    end = today if args.include_today else today - timedelta(days=1)
    dailies = load_dailies(args.reports, None, end)[-max(1, args.issues) :]
    rows = reported_events(dailies)
    print(json.dumps(rows, ensure_ascii=False, indent=2) if args.json else _format_ledger(rows, len(dailies)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

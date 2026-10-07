"""ledger.py 离线测试。零网络、零第三方依赖。

跑法（二选一）：
    python tests/test_ledger.py
    pytest tests/test_ledger.py
"""

import importlib.util
import io
import json
import sys
import tempfile
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "ledger.py"
_spec = importlib.util.spec_from_file_location("ledger", _SCRIPT)
ledger = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ledger)


def _daily(must, notable=(), followups=()):
    lines = ["# AI 情报日报", "", "## 🔥 今日必读", ""]
    for i, (title, url, score) in enumerate(must, 1):
        lines += [f"**{i}. [{title}]({url})** `{score}/10` · 2 源 · 媒体", "⚡ x", "👉 y", ""]
    lines += ["## 📌 值得关注", ""]
    lines += [f"- **[{t}]({u})** `{s}` · 产品动态 · 媒体" for t, u, s in notable]
    if followups:
        lines += ["", "## 🔁 续报", ""] + [f"- **[{t}]({u})** · 首报 10-05 · 官方" for t, u in followups]
    return "\n".join(lines) + "\n"


def _make_archive(d: Path):
    (d / "daily-2026-10-05.md").write_text(
        _daily([("OpenAI 取消发布 Astra", "https://ex.com/a", 10), ("事件 B", "https://ex.com/b", 8)], [("事件 C", "https://ex.com/c", 7)]),
        encoding="utf-8",
    )
    (d / "daily-2026-10-06.md").write_text(
        _daily([("OpenAI 取消发布 Astra 后续", "https://ex.com/a/", 9)], [("事件 D", "https://ex.com/d", 6)], [("事件 B 进展", "https://ex.com/b2")]),
        encoding="utf-8",
    )
    (d / "daily-2026-10-07.md").write_text(_daily([("今天的事件 E", "https://ex.com/e", 9)]), encoding="utf-8")
    (d / "weekly-2026-W41.md").write_text("# 不应被台账读取\n", encoding="utf-8")


def test_reported_excludes_today_and_sorts_desc():
    with tempfile.TemporaryDirectory() as d:
        _make_archive(Path(d))
        dailies = ledger.load_dailies(d, None, date(2026, 10, 6))
        rows = ledger.reported_events(dailies)
    assert [(r["date"], r["title"]) for r in rows] == [
        ("2026-10-06", "OpenAI 取消发布 Astra 后续"),
        ("2026-10-05", "OpenAI 取消发布 Astra"),
        ("2026-10-05", "事件 B"),
    ]
    assert rows[0]["coverage"] == 2 and rows[0]["importance"] == 9


def test_main_ledger_window_options():
    with tempfile.TemporaryDirectory() as d:
        _make_archive(Path(d))
        for extra, expect_in, expect_out in (
            ([], "事件 B", "今天的事件 E"),
            (["--include-today"], "今天的事件 E", None),
            (["--issues", "1"], "Astra 后续", "事件 B"),
        ):
            buf = io.StringIO()
            with redirect_stdout(buf):
                assert ledger.main(["--reports", d, "--today", "2026-10-07", "--json"] + extra) == 0
            titles = [r["title"] for r in json.loads(buf.getvalue())]
            assert any(expect_in in t for t in titles), (extra, titles)
            if expect_out:
                assert not any(expect_out == t for t in titles), (extra, titles)


def test_compile_merges_same_event_across_days_and_ranks():
    with tempfile.TemporaryDirectory() as d:
        _make_archive(Path(d))
        groups = ledger.compile_candidates(ledger.load_dailies(d, date(2026, 10, 5), date(2026, 10, 7)), top=10)
    first = groups[0]
    assert first["url"] == "https://ex.com/a"  # 两天都是头条，跨天合并
    assert first["days"] == ["2026-10-05", "2026-10-06"] and first["score"] == 10
    assert first["max_importance"] == 10
    assert [g["title"] for g in groups[1:3]] == ["今天的事件 E", "事件 B"]
    assert len(groups) == 6  # A, E, B, C, D, B 进展（标题不同、链接不同 → 另算一件）


def test_compile_merges_by_title_similarity():
    rep1 = {"must": [{"rank": 1, "title": "Mistral 发布 Large 4 开源旗舰", "url": "https://a.com/1", "importance": 8}]}
    rep2 = {"must": [{"rank": 2, "title": "Mistral 发布 Large 4 开源旗舰模型", "url": "https://b.com/2", "importance": 8}]}
    groups = ledger.compile_candidates([(date(2026, 10, 6), rep1), (date(2026, 10, 7), rep2)])
    assert len(groups) == 1 and groups[0]["score"] == 8 and len(groups[0]["days"]) == 2


def test_prefers_sidecar_json_when_present():
    with tempfile.TemporaryDirectory() as d:
        _make_archive(Path(d))
        side = {"schema": ledger.SCHEMA, "must": [{"rank": 1, "title": "来自 JSON", "url": "https://ex.com/j", "importance": 9, "coverage": 4}]}
        (Path(d) / "daily-2026-10-05.json").write_text(json.dumps(side, ensure_ascii=False), encoding="utf-8")
        dailies = ledger.load_dailies(d, date(2026, 10, 5), date(2026, 10, 5))
    assert dailies[0][1]["must"][0]["title"] == "来自 JSON"


# ── 零依赖 runner ──
def _main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_main())

"""verify_report.py 离线测试。零网络、零第三方依赖。

跑法（二选一）：
    python tests/test_verify_report.py
    pytest tests/test_verify_report.py
"""

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "verify_report.py"
_spec = importlib.util.spec_from_file_location("verify_report", _SCRIPT)
vr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vr)


REPORT = """# AI 情报日报 · 2026-10-08

## ⚡ 今日速览

速览一句。

## 🔥 今日必读

**1. [事件 A](https://ex.com/a)** `9/10` · 3 源 · 官方 / 媒体
⚡ so-what
👉 action

**2. [事件 B](https://ex.com/b/)** `8/10` · 媒体
⚡ so-what

## 📌 值得关注

- **[事件 C](http://www.ex.com/c?utm_source=x)** `7` · 商业资本 · TechCrunch
- **[事件 D](https://ex.com/d)** `6` · 产研工具 · GitHub / Vercel

## 🔁 续报

- **[事件 A 进展](https://ex.com/a2)** · 首报 10-07 · 官方

## 🔧 GitHub 开源雷达

| 项目 | ⭐ | 定位 |
|---|---|---|
| [owner/repo](https://github.com/owner/repo) | 31.3k | 决策引擎 |

**① [own2/rep2](https://github.com/own2/rep2)** ⭐1.2k · Python · `x`

---

## 📚 附录 · 深度解读

> 来源：[官方](https://ex.com/a) · 重要度 9/10
"""

EVIDENCE = {
    "https://ex.com/a",
    "https://ex.com/b",
    "https://ex.com/c",
    "https://ex.com/d",
    "https://ex.com/a2",
    "https://github.com/owner/repo",
    "https://github.com/own2/rep2",
}


def _evidence(exclude=()):
    return {vr.normalize_url(u) for u in EVIDENCE if u not in exclude}


def test_normalize_url_equivalents():
    base = "https://ex.com/path"
    for variant in (
        "https://ex.com/path/",
        "http://ex.com/path",
        "https://www.ex.com/path",
        "https://ex.com/path?utm_source=x&utm_medium=y",
        "https://ex.com/path\\",
        "https://ex.com:443/path",
        "https://ex.com/path#section",
    ):
        assert vr.normalize_url(variant) == vr.normalize_url(base), variant
    # 有实义的参数保留
    assert vr.normalize_url("https://ex.com/item?id=1") != vr.normalize_url("https://ex.com/item?id=2")
    assert vr.normalize_url("https://x.com/sama/status/1?lang=en") == vr.normalize_url("https://x.com/sama/status/1")


def test_extract_links_with_line_numbers():
    links = vr.extract_links("a [x](https://a.com/1) b\nc <https://b.com/2>\n")
    assert links == [(1, "https://a.com/1"), (2, "https://b.com/2")]


def test_load_evidence_from_radar_and_url_list():
    with tempfile.TemporaryDirectory() as d:
        radar = Path(d) / "radar.json"
        radar.write_text(json.dumps({"items": [{"url": "https://ex.com/a/"}, {"title": "no url"}]}), encoding="utf-8")
        urls = Path(d) / "verified_urls.txt"
        urls.write_text("# 检索记录\nhttps://ex.com/b\n\n  https://ex.com/c?utm_source=z  \n", encoding="utf-8")
        ev = vr.load_evidence([radar], [urls])
    assert ev == {vr.normalize_url(u) for u in ("https://ex.com/a", "https://ex.com/b", "https://ex.com/c")}


def test_check_passes_when_all_links_have_evidence():
    res = vr.check_report(REPORT, _evidence())
    assert res["unverified"] == []
    assert res["foreign"] == []
    assert not vr.has_errors(res)


def test_check_flags_link_without_evidence():
    res = vr.check_report(REPORT, _evidence(exclude={"https://ex.com/d"}))
    assert [u for _, u in res["unverified"]] == ["https://ex.com/d"]
    assert vr.has_errors(res)


def test_check_flags_foreign_script_chars():
    res = vr.check_report("## 🔥 今日必读\n入价维持 типed 决策\n", set())
    assert res["foreign"] and "т" in res["foreign"][0][1]
    assert vr.has_errors(res)


def test_check_warns_param_conversion_not_money():
    text = "总参数 5010 亿、激活 230 亿，视觉编码器 16 亿参数；融资 40 亿美元。"
    found = [v for _, v in vr.check_report(text, set())["param_conversion"]]
    assert found == ["5010 亿", "230 亿", "16 亿"]


def test_check_warns_must_read_without_coverage():
    res = vr.check_report(REPORT, _evidence())
    lines = REPORT.splitlines()
    assert len(res["missing_coverage"]) == 1
    assert "事件 B" in lines[res["missing_coverage"][0] - 1]
    assert not vr.has_errors(res)  # 只是警告


def test_parse_report_structure():
    rep = vr.parse_report(REPORT, "daily-2026-10-08.md")
    assert (rep["range"], rep["period"]) == ("daily", "2026-10-08")
    assert [m["rank"] for m in rep["must"]] == [1, 2]
    a = rep["must"][0]
    assert (a["title"], a["importance"], a["coverage"], a["sources"]) == ("事件 A", 9, 3, "官方 / 媒体")
    assert rep["must"][1]["coverage"] is None
    c = rep["notable"][0]
    assert (c["importance"], c["category"], c["sources"]) == (7, "商业资本", "TechCrunch")
    lone = vr.parse_report("## 📌 值得关注\n- **[X](https://ex.com/x)** `6` · 彭博\n")["notable"][0]
    assert (lone["category"], lone["sources"]) == (None, "彭博")  # 漏写分类不吞来源
    assert rep["followups"][0]["title"] == "事件 A 进展"
    assert [g["repo"] for g in rep["github"]] == ["owner/repo", "own2/rep2"]
    assert rep["github"][0]["stars"] == "31.3k"


def test_main_exit_codes_and_json_output():
    with tempfile.TemporaryDirectory() as d:
        report = Path(d) / "daily-2026-10-08.md"
        report.write_text(REPORT, encoding="utf-8")
        urls = Path(d) / "verified_urls.txt"

        urls.write_text("\n".join(sorted(EVIDENCE - {"https://ex.com/d"})), encoding="utf-8")
        assert vr.main([str(report), "--urls", str(urls), "--emit-json"]) == 1
        assert not report.with_suffix(".json").exists()  # 未通过不导出

        urls.write_text("\n".join(sorted(EVIDENCE)), encoding="utf-8")
        out = Path(d) / "side.json"
        assert vr.main([str(report), "--urls", str(urls), "--json-out", str(out)]) == 0
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["schema"] == vr.SCHEMA and data["links"]["total"] == data["links"]["verified"]

        assert vr.main([str(report), "--parse-only", "--emit-json"]) == 0
        assert json.loads(report.with_suffix(".json").read_text(encoding="utf-8"))["links"]["verified"] is None


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

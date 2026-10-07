"""gold_eval.py 离线测试。零网络、零第三方依赖。

跑法（二选一）：
    python tests/test_gold_eval.py
    pytest tests/test_gold_eval.py
"""

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "gold_eval.py"
_spec = importlib.util.spec_from_file_location("gold_eval", _SCRIPT)
ge = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ge)

_SEED = Path(__file__).resolve().parent / "gold" / "seed.jsonl"


def _g(cid, bucket, split="dev"):
    return {"caseId": cid, "material": {"title": f"t-{cid}"}, "split": split, "stratum": "s", "gold": {"bucket": bucket}}


GOLD = [_g("m1", "must"), _g("m2", "must"), _g("n1", "notable"), _g("s1", "skip"), _g("e1", "either"), _g("h1", "must", "holdout")]


def test_bucket_of():
    assert ge.bucket_of({"importance": 8}, 8, 6) == "must"
    assert ge.bucket_of({"importance": 7}, 8, 6) == "notable"
    assert ge.bucket_of({"importance": 5}, 8, 6) == "skip"
    assert ge.bucket_of({"bucket": "notable"}, 8, 6) == "notable"
    assert ge.bucket_of(None, 8, 6) is None
    assert ge.bucket_of({"importance": "高"}, 8, 6) is None


def test_perfect_predictions():
    preds = [{"caseId": "m1", "importance": 9}, {"caseId": "m2", "importance": 8}, {"caseId": "n1", "importance": 6}, {"caseId": "s1", "importance": 3}]
    m = ge.evaluate(GOLD, preds, split="dev")
    assert m["n_cases"] == 5 and m["n_scored"] == 4 and m["n_either"] == 1  # either 不计分
    assert m["accuracy"] == 1.0 and m["n_missing"] == 0
    assert m["per_class"]["must"]["precision"] == 1.0 and m["per_class"]["must"]["recall"] == 1.0


def test_errors_missing_and_sweep():
    preds = [{"caseId": "m1", "importance": 9}, {"caseId": "m2", "importance": 7}, {"caseId": "n1", "importance": 8}]  # s1 缺预测
    m = ge.evaluate(GOLD, preds, split="dev")
    assert m["accuracy"] == 0.25
    assert m["n_missing"] == 1 and m["confusion"]["skip"]["missing"] == 1
    assert {x["caseId"] for x in m["mismatches"]} == {"m2", "n1", "s1"}
    must = m["per_class"]["must"]
    assert must["precision"] == 0.5 and must["recall"] == 0.5
    sweep = {s["must_threshold"]: s for s in m["must_sweep"]}
    assert sweep[7]["recall"] == 1.0 and sweep[7]["selected"] == 3
    assert sweep[9]["precision"] == 1.0 and sweep[9]["recall"] == 0.5


def test_zero_precision_gives_zero_f1():
    m = ge.evaluate([_g("a", "skip"), _g("b", "must")], [{"caseId": "a", "importance": 9}, {"caseId": "b", "importance": 2}])
    assert m["per_class"]["must"]["precision"] == 0.0 and m["per_class"]["must"]["f1"] == 0.0


def test_split_filter():
    m = ge.evaluate(GOLD, [{"caseId": "h1", "importance": 8}], split="holdout")
    assert m["n_cases"] == 1 and m["accuracy"] == 1.0


def test_main_reads_files_and_rejects_bad_json():
    with tempfile.TemporaryDirectory() as d:
        gold, pred = Path(d) / "g.jsonl", Path(d) / "p.jsonl"
        gold.write_text("\n".join(json.dumps(g, ensure_ascii=False) for g in GOLD), encoding="utf-8")
        pred.write_text(json.dumps({"caseId": "m1", "importance": 9}), encoding="utf-8")
        assert ge.main(["--gold", str(gold), "--pred", str(pred), "--json"]) == 0
        pred.write_text("{not json", encoding="utf-8")
        assert ge.main(["--gold", str(gold), "--pred", str(pred)]) == 2


def test_seed_file_schema():
    rows = ge.load_jsonl(_SEED)
    ids = [r["caseId"] for r in rows]
    assert len(ids) == len(set(ids)), "caseId 必须唯一"
    for r in rows:
        assert r["gold"]["bucket"] in ge.CLASSES + ("either",), r["caseId"]
        assert r["split"] in ("dev", "holdout"), r["caseId"]
        mat = r["material"]
        assert mat.get("title") and mat.get("source") and mat.get("url", "").startswith("http"), r["caseId"]
    buckets = {b: sum(1 for r in rows if r["gold"]["bucket"] == b) for b in ge.CLASSES}
    assert all(n >= 5 for n in buckets.values()), buckets
    assert any(r["split"] == "holdout" for r in rows)


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

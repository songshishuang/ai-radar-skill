#!/usr/bin/env python3
"""ai-radar 报告出处校验 + 结构化导出（纯标准库）。

落盘前跑一遍：报告里的每个链接都必须能在「本期素材」里找到——
fetch.py 的输出（radar.json）或宿主 agent 记录下来的检索链接（verified_urls.txt）。
找不到的链接一律视为「无出处」，脚本返回 1，必须改掉再落盘。

用法:
    python verify_report.py REPORT.md --evidence radar.json --urls verified_urls.txt
    python verify_report.py REPORT.md --evidence radar.json --urls verified_urls.txt --emit-json
    python verify_report.py REPORT.md --parse-only --json-out /path/sidecar.json   # 只解析（补历史报告的 JSON）

检查项:
    错误（返回 1，必须修）: 无出处链接；混入西里尔 / 阿拉伯 / 泰 / 韩 / 天城等异体文字
    警告（不阻断，建议修）: 参数量被换算成中文数量词（如 49B 写成 490 亿）；必读条目未标「N 源」

--emit-json 在校验通过后，把报告解析成结构化 JSON（默认与报告同名 .json），
供 ledger.py 做跨期去重 / 周报汇编、京ME 卡片等复用。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SCHEMA = "ai-radar/report@1"

_DROP_PARAMS = {"ref", "ref_src", "lang", "s", "fbclid", "gclid"}
_LINK_RE = re.compile(r"\]\((https?://[^)\s]+)\)")
_AUTOLINK_RE = re.compile(r"<(https?://[^>\s]+)>")
_FOREIGN_RE = re.compile(r"[Ѐ-ӿ؀-ۿऀ-ॿ฀-๿가-힯]")
_PARAM_CONV_RE = re.compile(
    r"(?:参数|激活)[^。；，,\n]{0,6}?(\d+(?:\.\d+)?\s*(?:万亿|亿))"
    r"|(\d+(?:\.\d+)?\s*(?:万亿|亿))(?=\s*(?:参数|激活))"
)
_COVERAGE_RE = re.compile(r"(\d+)\s*源")

_MUST_RE = re.compile(r"^\*\*(\d+)\.\s*\[(.+?)\]\((https?://[^)\s]+)\)\*\*\s*`(\d+)/10`(.*)$")
_NOTABLE_RE = re.compile(r"^-\s*\*\*\[(.+?)\]\((https?://[^)\s]+)\)\*\*\s*`(\d+)`(.*)$")
_FOLLOW_RE = re.compile(r"^-\s*\**\[(.+?)\]\((https?://[^)\s]+)\)\**(.*)$")
_GH_TABLE_RE = re.compile(r"^\|\s*\[([\w.-]+/[\w.-]+)\]\((https?://[^)\s]+)\)\s*\|\s*([\d.]+k?)\s*\|")
_GH_CARD_RE = re.compile(r"^\*\*\S*?\s*\[([\w.-]+/[\w.-]+)\]\((https?://[^)\s]+)\)\*\*\s*⭐\s*([\d.]+k?)")
_FILE_RE = re.compile(r"^(daily|weekly|monthly)-(.+)$")


def normalize_url(url: str) -> str:
    """把等价写法归一，避免因末尾斜杠、跟踪参数、http/https、www 前缀误判无出处。"""
    u = url.strip().rstrip("\\").rstrip(".,;:")
    try:
        p = urlsplit(u)
    except ValueError:
        return u
    scheme = "https" if p.scheme in ("http", "https") else p.scheme
    host = p.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if host.endswith((":443", ":80")):
        host = host.rsplit(":", 1)[0]
    query = urlencode(
        [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not k.lower().startswith("utm_") and k.lower() not in _DROP_PARAMS]
    )
    return urlunsplit((scheme, host, p.path.rstrip("/"), query, ""))


def extract_links(text: str) -> list:
    """返回 [(行号, url)]：Markdown 链接目标与 <https://...> 自动链接。"""
    out = []
    for ln, line in enumerate(text.splitlines(), 1):
        out.extend((ln, m.group(1)) for m in _LINK_RE.finditer(line))
        out.extend((ln, m.group(1)) for m in _AUTOLINK_RE.finditer(line))
    return out


def load_evidence(radar_paths=(), url_list_paths=()) -> set:
    """本期素材链接集合：radar.json 的 items[].url + verified_urls.txt 每行一个链接（# 开头为注释）。"""
    urls = set()
    for p in radar_paths:
        data = json.loads(Path(p).read_text(encoding="utf-8"))
        urls.update(normalize_url(it["url"]) for it in data.get("items", []) if it.get("url"))
    for p in url_list_paths:
        for line in Path(p).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = re.search(r"https?://\S+", line)
            if m:
                urls.add(normalize_url(m.group(0)))
    return urls


def _section_kind(heading: str):
    if "必读" in heading or "重大事件" in heading:
        return "must"
    if "值得关注" in heading:
        return "notable"
    if "续报" in heading:
        return "followups"
    if "GitHub" in heading:
        return "github"
    return None


def _split_rest(rest: str) -> list:
    return [p.strip() for p in rest.split("·") if p.strip()]


def parse_report(text: str, filename: str | None = None) -> dict:
    """把金字塔报告解析成结构化 dict（只认模板里的正文行，不解析附录）。"""
    stem = Path(filename).stem if filename else ""
    m = _FILE_RE.match(stem)
    rep = {
        "schema": SCHEMA,
        "file": Path(filename).name if filename else None,
        "range": m.group(1) if m else None,
        "period": m.group(2) if m else None,
        "must": [],
        "notable": [],
        "followups": [],
        "github": [],
    }
    section = None
    for line in text.splitlines():
        if line.startswith("## "):
            section = _section_kind(line[3:])
            continue
        if section == "must" and (mm := _MUST_RE.match(line)):
            parts = _split_rest(mm.group(5))
            cov = next((int(c.group(1)) for p in parts if (c := _COVERAGE_RE.fullmatch(p))), None)
            rep["must"].append(
                {
                    "rank": int(mm.group(1)),
                    "title": mm.group(2),
                    "url": mm.group(3),
                    "importance": int(mm.group(4)),
                    "coverage": cov,
                    "sources": " · ".join(p for p in parts if not _COVERAGE_RE.fullmatch(p)),
                }
            )
        elif section == "notable" and (mm := _NOTABLE_RE.match(line)):
            parts = _split_rest(mm.group(4))
            if len(parts) == 1:  # 漏写分类时唯一一段按来源处理
                parts = [None] + parts
            rep["notable"].append(
                {
                    "title": mm.group(1),
                    "url": mm.group(2),
                    "importance": int(mm.group(3)),
                    "category": parts[0] if parts else None,
                    "sources": " · ".join(parts[1:]),
                }
            )
        elif section == "followups" and (mm := _FOLLOW_RE.match(line)):
            rep["followups"].append({"title": mm.group(1), "url": mm.group(2), "note": " · ".join(_split_rest(mm.group(3)))})
        elif section == "github" and (mm := _GH_TABLE_RE.match(line) or _GH_CARD_RE.match(line)):
            rep["github"].append({"repo": mm.group(1), "url": mm.group(2), "stars": mm.group(3)})
    return rep


def check_report(text: str, evidence: set | None) -> dict:
    """evidence=None 表示只解析不校验出处（--parse-only）。"""
    links = extract_links(text)
    unverified = [] if evidence is None else [(ln, u) for ln, u in links if normalize_url(u) not in evidence]
    foreign, param_conv, missing_cov = [], [], []
    section = None
    for ln, line in enumerate(text.splitlines(), 1):
        if line.startswith("## "):
            section = _section_kind(line[3:])
        plain = _AUTOLINK_RE.sub("", _LINK_RE.sub("](URL)", line))
        chars = sorted({m.group(0) for m in _FOREIGN_RE.finditer(plain)})
        if chars:
            foreign.append((ln, "".join(chars)))
        param_conv.extend((ln, (m.group(1) or m.group(2)).strip()) for m in _PARAM_CONV_RE.finditer(plain))
        if section == "must" and (mm := _MUST_RE.match(line)) and not _COVERAGE_RE.search(mm.group(5)):
            missing_cov.append(ln)
    return {
        "links_total": len(links),
        "unverified": unverified,
        "foreign": foreign,
        "param_conversion": param_conv,
        "missing_coverage": missing_cov,
        "verified": evidence is not None,
    }


def has_errors(res: dict) -> bool:
    return bool(res["unverified"] or res["foreign"])


def format_result(res: dict) -> str:
    lines = []
    if res["verified"]:
        n_bad = len(res["unverified"])
        lines.append(f"出处校验：{res['links_total']} 个链接，已核实 {res['links_total'] - n_bad}，无出处 {n_bad}")
        lines += [f"  ✗ 第 {ln} 行：{u}" for ln, u in res["unverified"]]
    else:
        lines.append(f"出处校验：已跳过（--parse-only），共 {res['links_total']} 个链接")
    if res["foreign"]:
        lines.append("异体文字：")
        lines += [f"  ✗ 第 {ln} 行混入：{chars}" for ln, chars in res["foreign"]]
    else:
        lines.append("异体文字：未发现")
    warns = [f"  ⚠ 第 {ln} 行：参数量写成了「{v}」——版本号与参数量保留原文写法（如 49B、1.6B）" for ln, v in res["param_conversion"]]
    warns += [f"  ⚠ 第 {ln} 行：必读条目未标注报道面（N 源）" for ln in res["missing_coverage"]]
    lines.append("警告：" if warns else "警告：无")
    lines += warns
    lines.append("结论：" + ("未通过——修正上面标 ✗ 的项后重跑" if has_errors(res) else "通过"))
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="ai-radar 报告出处校验 + 结构化导出")
    ap.add_argument("report", help="报告 Markdown 路径")
    ap.add_argument("--evidence", action="append", default=[], help="fetch.py 输出的 radar.json，可多次传入")
    ap.add_argument("--urls", action="append", default=[], help="检索得到并已采用的链接清单，每行一个，可多次传入")
    ap.add_argument("--parse-only", action="store_true", help="只解析导出、不校验出处（用于补历史报告的 JSON）")
    ap.add_argument("--emit-json", action="store_true", help="通过后在报告旁写同名 .json")
    ap.add_argument("--json-out", help="结构化 JSON 写到指定路径（隐含 --emit-json）")
    args = ap.parse_args(argv)

    report = Path(args.report)
    try:
        text = report.read_text(encoding="utf-8")
        evidence = None if args.parse_only else load_evidence(args.evidence, args.urls)
    except (OSError, ValueError) as e:
        print(f"读取失败：{e}", file=sys.stderr)
        return 2

    res = check_report(text, evidence)
    print(format_result(res))
    if has_errors(res):
        return 1

    if args.emit_json or args.json_out:
        out = Path(args.json_out) if args.json_out else report.with_suffix(".json")
        data = parse_report(text, report.name)
        data["links"] = {"total": res["links_total"], "verified": None if args.parse_only else res["links_total"]}
        out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"结构化 JSON：{out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

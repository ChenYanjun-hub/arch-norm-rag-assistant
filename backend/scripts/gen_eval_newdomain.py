"""W7 D9：为新域（市政/结构）生成 chunk-grounded 评测候选。

方法（守 RED LINE 2：expected 答案不编造）：
  对目标域规范挑「强制性 + 含数值」的真实 chunk → DeepSeek 据此生成自然 query
  → expected_spec/clause/answer 全部取自该 chunk 原文。

输出：data/eval/_candidates_newdomain.csv（供用户抽查；审核后 build 进正式集）

用法：
    python -m scripts.gen_eval_newdomain --domains 市政,结构 --per-spec 2 --target 25
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import time
from pathlib import Path

from openai import OpenAI

from app.core.config import settings

_HERE = Path(__file__).resolve().parent
CHUNKS_DIR = _HERE.parent / "data" / "chunks"
OUT = _HERE.parent / "data" / "eval" / "_candidates_newdomain.csv"

GEN_PROMPT = """你是设计规范评测集构建助手。给你一条规范条文，请生成一个【设计师会自然提出的中文查询问题】，该问题的答案正好落在这条条文里。

要求：
1. 口语自然，像设计师查规范时真的会问的
2. 不要在问题里直接抄答案的具体数值/结论（避免泄题）
3. 一句话，≤40 字，只输出问题本身，不要任何解释或引号

规范：{spec_name}（{spec_code}）{clause}
条文：{text}"""

_NUM_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:m²|m³|m|km|%|kV|MPa|kN|度|年|人|床|班|辆|座|个|处|级|min|s|h|t)")


def _has_number(text: str) -> bool:
    return bool(_NUM_RE.search(text))


def _key_elements(text: str) -> str:
    """抽取数值+单位作为 key_elements（评测核对点）。"""
    nums = _NUM_RE.findall(text)
    return " / ".join(dict.fromkeys(nums))[:80]  # 去重保序


def _load_domain_chunks(domains: set[str]) -> dict[str, list[dict]]:
    """按 spec_code 分组目标域 chunks。"""
    by_spec: dict[str, list[dict]] = {}
    for jf in sorted(CHUNKS_DIR.glob("*.json")):
        if jf.name.startswith("_"):
            continue
        arr = json.loads(jf.read_text(encoding="utf-8"))
        if not arr or not isinstance(arr[0], dict):
            continue
        if arr[0].get("domain") not in domains:
            continue
        for ck in arr:
            if not isinstance(ck, dict):
                continue
            by_spec.setdefault(ck["spec_code"], []).append(ck)
    return by_spec


def _select(chunks: list[dict], per_spec: int) -> list[dict]:
    """挑高价值 chunk：强制性 + 含数值 + 长度适中，优先。"""
    def score(c: dict) -> tuple:
        t = c.get("text", "")
        return (
            c.get("is_mandatory", False),
            _has_number(t),
            50 <= len(t) <= 450,  # 太短信息少、太长不聚焦
            c.get("type") == "clause",
        )
    ranked = sorted(chunks, key=lambda c: sum(score(c)), reverse=True)
    return ranked[:per_spec]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--domains", default="市政,结构")
    ap.add_argument("--per-spec", type=int, default=2)
    ap.add_argument("--target", type=int, default=25)
    ap.add_argument("--specs", default="",
                    help="逗号分隔 spec_code，只为这些规范生成（留空=整域）；用于精准补覆盖缺口")
    args = ap.parse_args()

    domains = set(args.domains.split(","))
    by_spec = _load_domain_chunks(domains)
    if args.specs:
        want = {s.strip() for s in args.specs.split(",") if s.strip()}
        missing = want - set(by_spec)
        if missing:
            print(f"⚠️ 这些 spec_code 未在目标域语料中找到: {sorted(missing)}")
        by_spec = {k: v for k, v in by_spec.items() if k in want}
    print(f"目标域 {domains}：{len(by_spec)} 部规范")

    # 每部挑 per_spec 条候选 chunk，再按 target 截断（轮转保证覆盖每部）
    picks: list[dict] = []
    per_spec_picks = {code: _select(cks, args.per_spec) for code, cks in by_spec.items()}
    round_i = 0
    while len(picks) < args.target and any(per_spec_picks.values()):
        for code in sorted(per_spec_picks):
            lst = per_spec_picks[code]
            if round_i < len(lst):
                picks.append(lst[round_i])
                if len(picks) >= args.target:
                    break
        round_i += 1

    print(f"选中 {len(picks)} 条 chunk，调 DeepSeek 生成 query...\n")
    client = OpenAI(api_key=settings.deepseek_api_key, base_url=settings.deepseek_base_url)

    rows = []
    for i, ck in enumerate(picks, 1):
        text = ck.get("text", "")
        try:
            resp = client.chat.completions.create(
                model=settings.deepseek_model,
                messages=[{"role": "user", "content": GEN_PROMPT.format(
                    spec_name=ck.get("spec_name", ""), spec_code=ck["spec_code"],
                    clause=ck.get("clause", ""), text=text[:500])}],
                temperature=0.4, timeout=30,
            )
            query = resp.choices[0].message.content.strip().strip('"" 　')
        except Exception as e:
            print(f"  [{i}] ❌ {ck['spec_code']}: {e}")
            continue
        rows.append({
            "id": f"QN{i:03d}",
            "scenario": "规范查找",
            "difficulty": "显性事实" if _has_number(text) else "隐性事实",
            "spec_domain": ck.get("domain", ""),
            "query": query,
            "expected_spec": ck["spec_code"],
            "expected_clause": ck.get("clause", ""),
            "expected_answer_summary": text[:120].replace("\n", " "),
            "key_elements": _key_elements(text),
            "trap_type": "",
        })
        print(f"  [{i}/{len(picks)}] {ck['spec_code']} {ck.get('clause','')}: {query[:34]}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\n✅ {len(rows)} 条候选 → {OUT.relative_to(_HERE.parent)}")


if __name__ == "__main__":
    main()

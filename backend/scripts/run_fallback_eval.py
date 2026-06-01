"""W4 D3 part 2：跑 fallback_set 验证 scenario.py 8 类识别准确率。

跟主评测脚本 run_eval.py 分离 —— 这里只测 scenario 层的"识别正确性"，
不调向量检索 / reranker / LLM。

用法（cwd = backend/）：
    .venv/bin/python -m scripts.run_fallback_eval

输出：
    - 控制台准确率表
    - data/eval/results/fallback_eval_<timestamp>.json
"""

from __future__ import annotations

import csv
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services.scenario import detect_scenario  # noqa: E402

CSV_PATH = _BACKEND / "data" / "eval" / "fallback_set_v1.csv"
OUT_DIR = _BACKEND / "data" / "eval" / "results"


def _materialize_query(raw: str) -> str:
    """处理特殊 marker（如 input_too_long 的 __GENERATE_500_PLUS__）。"""
    if raw == "__GENERATE_500_PLUS__":
        return "查询规范" * 150  # ~600 字 > 500 阈值
    return raw


def main() -> None:
    if not CSV_PATH.exists():
        print(f"❌ CSV 不存在：{CSV_PATH}", file=sys.stderr)
        sys.exit(1)

    rows = list(csv.DictReader(open(CSV_PATH, encoding="utf-8")))
    n_total = len(rows)
    print(f"\n🎯 Fallback 识别评测 · n={n_total}\n")
    print(f"{'ID':4} | {'期望':14} | {'实际':14} | {'query':35} | 状态")
    print("-" * 88)

    results: list[dict] = []
    correct = 0
    soft_pass = 0  # no_result 走 normal 算"软通过"
    by_scenario: dict[str, dict[str, int]] = defaultdict(
        lambda: {"total": 0, "hit": 0, "soft": 0}
    )

    for r in rows:
        qid = r["id"]
        exp = r["expected_scenario"]
        q = _materialize_query(r["query"])
        actual = detect_scenario(q)
        query_show = (q[:33] + "…") if len(q) > 33 else q
        if not q.strip() and q:
            query_show = repr(q[:20])

        by_scenario[exp]["total"] += 1
        if actual == exp:
            correct += 1
            by_scenario[exp]["hit"] += 1
            flag = "✅"
        elif exp == "no_result" and actual == "normal":
            soft_pass += 1
            by_scenario[exp]["soft"] += 1
            flag = "⚠️ 走RAG兜底"
        else:
            flag = "❌"

        results.append(
            {
                "id": qid,
                "expected": exp,
                "actual": actual,
                "query": q[:60],
                "test_intent": r.get("test_intent", ""),
                "pass": actual == exp,
                "soft_pass": exp == "no_result" and actual == "normal",
            }
        )
        print(f"{qid:4} | {exp:14} | {actual:14} | {query_show:35} | {flag}")

    print("\n" + "=" * 88)
    print(f"✅ 严格通过：{correct}/{n_total} ({correct/n_total:.0%})")
    print(f"⚠️ 软通过（no_result→normal 走 RAG 兜底）：{soft_pass}/{n_total}")
    print(f"❌ 失败：{n_total - correct - soft_pass}/{n_total}")

    print(f"\n按场景类型：")
    print(f"  {'场景':14} | {'总':3} | {'命中':3} | {'软过':3} | 准确率")
    for sc in sorted(by_scenario.keys()):
        s = by_scenario[sc]
        rate = s["hit"] / s["total"] if s["total"] else 0
        print(f"  {sc:14} | {s['total']:3} | {s['hit']:3} | {s['soft']:3} | {rate:.0%}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    out_path = OUT_DIR / f"fallback_eval_{ts}.json"
    out_path.write_text(
        json.dumps(
            {
                "timestamp": ts,
                "n_total": n_total,
                "strict_pass": correct,
                "soft_pass": soft_pass,
                "fail": n_total - correct - soft_pass,
                "by_scenario": {sc: dict(s) for sc, s in by_scenario.items()},
                "rows": results,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n💾 JSON 报告：{out_path}")


if __name__ == "__main__":
    main()

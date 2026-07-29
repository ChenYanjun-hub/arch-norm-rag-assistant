"""Agent 路由评测（W7 · agent 深化 Router）。

评测 agent_router 的路由决策质量。与 run_eval（检索层）/ run_quality_eval（生成层）
/ run_fallback_eval（兜底）并列，补上「agent 行为」这一层评测。

用法（cwd = backend/，不需要 Qdrant，纯规则、秒级）：
    python -m scripts.run_agent_eval
    python -m scripts.run_agent_eval --csv data/eval/agent_route_set_v1.csv

指标：
    路由准确率          —— 整体 / 仅 clear 样本（borderline 单列，避免噪声掩盖真实水平）
    每类召回率 & 精确率 —— tool / decompose / plain
    误触发率（关键）    —— 本该 plain 却被路由去 tool/decompose（白付 LLM 成本 + 可能答偏）
    漏触发率            —— 本该 tool/decompose 却退回 plain（无损降级，可接受）
    混淆矩阵            —— 看错在哪
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from collections import defaultdict
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services.agent_router import resolve_route, route  # noqa: E402

DEFAULT_CSV = _BACKEND / "data" / "eval" / "agent_route_set_v1.csv"
ROUTES = ("tool", "decompose", "plain")


def main() -> None:
    parser = argparse.ArgumentParser(description="Agent 路由评测")
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--show-errors", action="store_true", default=True)
    parser.add_argument(
        "--llm",
        action="store_true",
        help="对规则模糊区升级到 LLM 判定（量化收益 vs 成本）",
    )
    args = parser.parse_args()

    if not args.csv.exists():
        print(f"❌ 评测集不存在：{args.csv}", file=sys.stderr)
        sys.exit(1)

    rows = list(csv.DictReader(args.csv.open(encoding="utf-8")))
    results = []
    t0 = time.time()
    for r in rows:
        got = resolve_route(r["query"], allow_llm=True) if args.llm else route(r["query"])
        results.append(
            {
                "id": r["id"],
                "query": r["query"],
                "expected": r["expected_route"].strip(),
                "got": got["route"],
                "reason": got["reason"],
                "difficulty": (r.get("difficulty") or "clear").strip(),
                "category": (r.get("category") or "").strip(),
                "ok": got["route"] == r["expected_route"].strip(),
            }
        )
    elapsed_ms = (time.time() - t0) * 1000

    n = len(results)
    clear = [x for x in results if x["difficulty"] == "clear"]
    border = [x for x in results if x["difficulty"] != "clear"]

    def acc(xs):
        return sum(x["ok"] for x in xs) / len(xs) if xs else 0.0

    mode = "规则+LLM兜模糊区" if args.llm else "纯规则"
    n_llm = sum(1 for x in results if x["reason"].startswith("模糊区经 LLM"))
    print(f"\n🎯 Agent 路由评测 · {args.csv.name} · {n} 条 · {mode} · {elapsed_ms:.0f}ms")
    if args.llm:
        print(f"   LLM 判定触发 {n_llm}/{n} 条（{n_llm / n * 100:.0f}%），其余 0ms 走规则\n")
    else:
        print()
    print(f"整体准确率      : {acc(results) * 100:.1f}%  ({sum(x['ok'] for x in results)}/{n})")
    print(f"clear 样本准确率: {acc(clear) * 100:.1f}%  ({sum(x['ok'] for x in clear)}/{len(clear)})")
    print(
        f"borderline 准确率: {acc(border) * 100:.1f}%  ({sum(x['ok'] for x in border)}/{len(border)})"
        "   ← 措辞误导型，反映误触发抵抗力"
    )

    # 每类 P/R
    print("\n每类指标：")
    print(f"{'路由':<12}{'样本':>5}{'召回':>9}{'精确':>9}")
    for rt in ROUTES:
        exp = [x for x in results if x["expected"] == rt]
        got = [x for x in results if x["got"] == rt]
        tp = sum(1 for x in exp if x["got"] == rt)
        recall = tp / len(exp) if exp else 0.0
        prec = tp / len(got) if got else 0.0
        print(f"{rt:<12}{len(exp):>5}{recall * 100:>8.1f}%{prec * 100:>8.1f}%")

    # 误触发 / 漏触发（本项目取舍：漏触发无损，误触发有损）
    should_plain = [x for x in results if x["expected"] == "plain"]
    false_trigger = [x for x in should_plain if x["got"] != "plain"]
    should_agent = [x for x in results if x["expected"] != "plain"]
    missed = [x for x in should_agent if x["got"] == "plain"]
    print(
        f"\n⚠️ 误触发率（该 plain 却调 agent，白付成本）: "
        f"{len(false_trigger) / len(should_plain) * 100:.1f}%  ({len(false_trigger)}/{len(should_plain)})"
    )
    print(
        f"○ 漏触发率（该 agent 却退 plain，无损降级）: "
        f"{len(missed) / len(should_agent) * 100:.1f}%  ({len(missed)}/{len(should_agent)})"
    )

    # 混淆矩阵
    cm: dict[tuple[str, str], int] = defaultdict(int)
    for x in results:
        cm[(x["expected"], x["got"])] += 1
    print("\n混淆矩阵（行=期望，列=实际）：")
    print(f"{'':<12}" + "".join(f"{c:>11}" for c in ROUTES))
    for e in ROUTES:
        print(f"{e:<12}" + "".join(f"{cm[(e, g)]:>11}" for g in ROUTES))

    if args.show_errors:
        errs = [x for x in results if not x["ok"]]
        if errs:
            print(f"\n错例（{len(errs)}）：")
            for x in errs:
                flag = "🔴误触发" if x["expected"] == "plain" else "🟡漏触发"
                if x["expected"] != "plain" and x["got"] != "plain":
                    flag = "🟠错路由"
                print(
                    f"  {flag} {x['id']} [{x['difficulty']}] {x['query'][:34]}\n"
                    f"       期望 {x['expected']} → 实际 {x['got']}（{x['reason']}）"
                )
        else:
            print("\n✅ 无错例")


if __name__ == "__main__":
    main()

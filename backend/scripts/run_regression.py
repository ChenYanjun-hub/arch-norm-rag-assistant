"""延迟回归测试 · 防假阳性（W4 D5，落地 AIPM v5.1 启示 39）。

背景
====
W4 D4 揭穿 W3 D2 multi-query "+2.6pp" 是 v2 评测集瑕疵造成的假阳性
（潜伏 4 天才被发现）。

本脚本自动化"评测集升级后逐个复测历史 SUCCESS 实验"的工程纪律：
   1. 在最新评测集上跑 6 组合矩阵（A-F）
   2. 对每个组合，找历史评测集（v2/v3 等）上同配置的 baseline
   3. Diff strict / loose 数字，标出"跨集翻转"（≥5pp 反向变化）
   4. 列出"在新评测集上不再有效"的实验

用法
====
    python -m scripts.run_regression                     # 默认 v3.1
    python -m scripts.run_regression --csv v3.1.csv
    python -m scripts.run_regression --use-cache         # 24h 内复用（默认）
    python -m scripts.run_regression --force-rerun       # 强制重跑

输出
====
    data/eval/regression/<timestamp>.md   人可读报告
    data/eval/regression/<timestamp>.json 机器可读
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

logger = logging.getLogger(__name__)

DEFAULT_CSV = _BACKEND / "data" / "eval" / "eval_set_v1_50_v3_1.csv"
RESULTS_DIR = _BACKEND / "data" / "eval" / "results"
REGRESSION_DIR = _BACKEND / "data" / "eval" / "regression"

# ── 6 组合矩阵 ───────────────────────────────────────────────
# A: 全开（最优配置候选）
# B: 只关 mq（看 mq 是否假阳性）
# C: 只关 rerank（看 rerank 双面性）
# D: 只关 mq + rerank（hybrid baseline）
# E: 只关 hybrid（W3 D3 复测）
# F: 全关（最纯净 baseline）
COMBOS: dict[str, dict[str, bool]] = {
    "A": {"mq": True,  "rk": True,  "hyb": True},
    "B": {"mq": False, "rk": True,  "hyb": True},
    "C": {"mq": True,  "rk": False, "hyb": True},
    "D": {"mq": False, "rk": False, "hyb": True},
    "E": {"mq": True,  "rk": True,  "hyb": False},
    "F": {"mq": False, "rk": False, "hyb": False},
}


@dataclass
class ComboResult:
    """单组合在某评测集上的结果。"""
    combo: str
    csv_name: str
    mq: bool
    rk: bool
    hyb: bool
    hit5_strict: float
    hit5_loose: float
    mrr_strict: float
    mrr_loose: float
    elapsed_s: float
    n_eval: int
    json_path: str
    timestamp: str


@dataclass
class CrossSetDiff:
    """同组合在新旧评测集上的对比。"""
    combo: str
    new_csv: str
    old_csv: str
    delta_strict: float
    delta_loose: float
    flipped: bool   # 是否翻转（≥5pp 反向）
    note: str


# ── 工具函数 ────────────────────────────────────────────────


def _load_results_index() -> list[dict[str, Any]]:
    """扫 results/ 目录所有 JSON，建结果索引（按 ctime 排序）。"""
    items: list[dict[str, Any]] = []
    for fp in sorted(RESULTS_DIR.glob("eval_v1_50_*.json")):
        try:
            data = json.load(open(fp, encoding="utf-8"))
        except Exception:
            continue
        cfg = data.get("config", {})
        ov = data.get("overall", {})
        items.append({
            "path": str(fp),
            "csv": Path(cfg.get("csv", "")).name or "unknown",
            "mq": bool(cfg.get("use_multi_query", False)),
            "rk": bool(cfg.get("use_rerank", False)),
            "hyb": bool(cfg.get("use_hybrid", False)),
            "ck": int(cfg.get("rerank_candidate_k", 20)),
            "pf": cfg.get("passage_format", "text_only"),
            "hit5_strict": float(ov.get("hit5_strict", 0)),
            "hit5_loose": float(ov.get("hit5_loose", 0)),
            "mrr_strict": float(ov.get("mrr_strict", 0)),
            "mrr_loose": float(ov.get("mrr_loose", 0)),
            "elapsed_s": float(cfg.get("elapsed_s", 0)),
            "n_eval": int(cfg.get("n_results", 0) or ov.get("n", 0)),
            "ts": cfg.get("timestamp", ""),
            "mtime": fp.stat().st_mtime,
        })
    return items


def _find_cached(
    index: list[dict[str, Any]],
    csv_name: str,
    combo: dict[str, bool],
    max_age_sec: int = 86400,
) -> dict[str, Any] | None:
    """在 results 索引里找匹配的最近结果（24h 内）。"""
    candidates = [
        it for it in index
        if it["csv"] == csv_name
        and it["mq"] == combo["mq"]
        and it["rk"] == combo["rk"]
        and it["hyb"] == combo["hyb"]
        and it["ck"] == 20         # baseline ck
        and it["pf"] == "text_only"  # baseline passage
    ]
    if not candidates:
        return None
    # 取最近的
    latest = max(candidates, key=lambda x: x["mtime"])
    if (time.time() - latest["mtime"]) > max_age_sec:
        return None
    return latest


def _run_combo(csv_path: Path, combo_key: str, combo: dict[str, bool]) -> dict[str, Any]:
    """跑一组合并返回结果。"""
    flags: list[str] = []
    if not combo["mq"]:
        flags.append("--no-multi-query")
    if not combo["rk"]:
        flags.append("--no-rerank")
    if not combo["hyb"]:
        flags.append("--no-hybrid")

    cmd = [
        sys.executable, "-m", "scripts.run_eval",
        "--csv", str(csv_path),
    ] + flags

    logger.info(f"[regression] 跑 {combo_key} {' '.join(flags) or '(all on)'}")
    result = subprocess.run(
        cmd, cwd=_BACKEND, capture_output=True, text=True
    )
    if result.returncode != 0:
        logger.error(f"[regression] {combo_key} 失败: {result.stderr[-500:]}")
        return {}

    # 找最新生成的 JSON
    items = _load_results_index()
    matched = [
        it for it in items
        if it["csv"] == csv_path.name
        and it["mq"] == combo["mq"]
        and it["rk"] == combo["rk"]
        and it["hyb"] == combo["hyb"]
    ]
    if not matched:
        logger.warning(f"[regression] {combo_key} 跑完但找不到新 JSON")
        return {}
    return max(matched, key=lambda x: x["mtime"])


def _detect_flips(
    new_csv: str,
    new_results: dict[str, dict[str, Any]],
    history: list[dict[str, Any]],
    flip_threshold: float = 0.05,
) -> list[CrossSetDiff]:
    """对每个组合，找历史评测集上同配置的最近结果做 diff。"""
    diffs: list[CrossSetDiff] = []
    for combo_key, new in new_results.items():
        combo = COMBOS[combo_key]
        # 找历史评测集（非当前集）上同配置的最近结果
        candidates = [
            h for h in history
            if h["csv"] != new_csv
            and h["mq"] == combo["mq"]
            and h["rk"] == combo["rk"]
            and h["hyb"] == combo["hyb"]
            and h["ck"] == 20
            and h["pf"] == "text_only"
        ]
        if not candidates:
            continue
        # 按 csv 分组，每个 csv 取最新
        by_csv: dict[str, dict[str, Any]] = {}
        for c in candidates:
            cur = by_csv.get(c["csv"])
            if cur is None or c["mtime"] > cur["mtime"]:
                by_csv[c["csv"]] = c
        for old_csv, old in by_csv.items():
            delta_strict = new["hit5_strict"] - old["hit5_strict"]
            delta_loose = new["hit5_loose"] - old["hit5_loose"]
            flipped = (abs(delta_strict) >= flip_threshold
                       or abs(delta_loose) >= flip_threshold)
            note = ""
            if abs(delta_loose) >= flip_threshold:
                if delta_loose < 0:
                    note = f"loose 跨集下降 {delta_loose*100:+.1f}pp（可能假阳性）"
                else:
                    note = f"loose 跨集上升 {delta_loose*100:+.1f}pp（评测集变可信）"
            elif abs(delta_strict) >= flip_threshold:
                note = f"strict 跨集变化 {delta_strict*100:+.1f}pp"
            diffs.append(CrossSetDiff(
                combo=combo_key,
                new_csv=new_csv,
                old_csv=old_csv,
                delta_strict=delta_strict,
                delta_loose=delta_loose,
                flipped=flipped,
                note=note,
            ))
    return diffs


# ── 主流程 ──────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="跨评测集回归测试（防假阳性）")
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument(
        "--combos", type=str, default="A,B,C,D,E,F",
        help="逗号分隔，如 'A,B,E'",
    )
    parser.add_argument(
        "--force-rerun", action="store_true",
        help="不复用 24h 内已有结果，强制重跑",
    )
    parser.add_argument(
        "--flip-threshold", type=float, default=0.05,
        help="跨集 diff 超过此值（绝对值）判定为翻转（默认 5pp）",
    )
    parser.add_argument("--out-dir", type=Path, default=REGRESSION_DIR)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    csv_path = args.csv
    if not csv_path.exists():
        print(f"❌ 评测集不存在：{csv_path}", file=sys.stderr)
        sys.exit(1)

    combos_to_run = [k.strip() for k in args.combos.split(",") if k.strip() in COMBOS]
    if not combos_to_run:
        print(f"❌ 没有有效 combo（可选 A-F）", file=sys.stderr)
        sys.exit(1)

    print(f"\n🔁 跨评测集回归测试")
    print(f"   评测集: {csv_path.name}")
    print(f"   组合: {','.join(combos_to_run)} ({len(combos_to_run)} 个)")
    print(f"   缓存策略: {'强制重跑' if args.force_rerun else '24h 内复用'}\n")

    index = _load_results_index()
    print(f"📚 历史 results 索引: {len(index)} 个 JSON\n")

    # ── Step 1: 跑当前评测集的 6 组合 ──
    new_results: dict[str, dict[str, Any]] = {}
    for ck in combos_to_run:
        combo = COMBOS[ck]
        # 尝试复用
        cached = None
        if not args.force_rerun:
            cached = _find_cached(index, csv_path.name, combo)
        if cached:
            print(f"  ⚡ {ck} 复用缓存: strict {cached['hit5_strict']:.1%} / "
                  f"loose {cached['hit5_loose']:.1%} ({cached['ts']})")
            new_results[ck] = cached
        else:
            print(f"  🆕 {ck} 跑评测...")
            result = _run_combo(csv_path, ck, combo)
            if result:
                print(f"     完成: strict {result['hit5_strict']:.1%} / loose {result['hit5_loose']:.1%}")
                new_results[ck] = result
                # 更新 index 让后续可用
                index = _load_results_index()

    if not new_results:
        print("❌ 没有有效结果", file=sys.stderr)
        sys.exit(1)

    # ── Step 2: 跨评测集 diff ──
    print(f"\n🔍 跨评测集 diff（阈值 ≥{args.flip_threshold*100:.0f}pp）\n")
    diffs = _detect_flips(csv_path.name, new_results, index, args.flip_threshold)

    flipped = [d for d in diffs if d.flipped]
    not_flipped = [d for d in diffs if not d.flipped]

    print(f"  ⚠️ 翻转配对: {len(flipped)}")
    print(f"  ✅ 稳定配对: {len(not_flipped)}")
    print()

    # ── Step 3: 输出报告 ──
    args.out_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    md_path = args.out_dir / f"regression_{ts}.md"
    json_path = args.out_dir / f"regression_{ts}.json"

    # JSON
    json_path.write_text(json.dumps({
        "csv": csv_path.name,
        "combos_run": combos_to_run,
        "flip_threshold": args.flip_threshold,
        "timestamp": ts,
        "new_results": {k: v for k, v in new_results.items()},
        "diffs": [asdict(d) for d in diffs],
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    # Markdown
    lines: list[str] = []
    lines.append(f"# 回归测试报告 · {csv_path.name}")
    lines.append("")
    lines.append(f"**生成时间**: {ts}")
    lines.append(f"**评测集**: `{csv_path.name}`")
    lines.append(f"**组合范围**: {','.join(combos_to_run)}")
    lines.append(f"**翻转阈值**: {args.flip_threshold*100:.0f}pp")
    lines.append("")
    lines.append("## 一、当前评测集 6 组合矩阵")
    lines.append("")
    lines.append("| Combo | mq | rk | hyb | Hit@5 strict | Hit@5 loose | MRR loose | 时延/条 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for ck in combos_to_run:
        r = new_results.get(ck, {})
        if not r: continue
        mq = "✅" if r["mq"] else "❌"
        rk = "✅" if r["rk"] else "❌"
        hyb = "✅" if r["hyb"] else "❌"
        elapsed_per = r["elapsed_s"] / max(r["n_eval"], 1)
        lines.append(f"| {ck} | {mq} | {rk} | {hyb} "
                     f"| {r['hit5_strict']:.1%} | {r['hit5_loose']:.1%} "
                     f"| {r['mrr_loose']:.3f} | {elapsed_per:.1f}s |")

    lines.append("")
    lines.append("## 二、跨评测集翻转检测")
    lines.append("")
    if flipped:
        lines.append("### ⚠️ 翻转配对（需复盘）")
        lines.append("")
        lines.append("| Combo | 新集 | 旧集 | Δ strict | Δ loose | 备注 |")
        lines.append("|---|---|---|---|---|---|")
        for d in flipped:
            lines.append(f"| {d.combo} | {d.new_csv} | {d.old_csv} "
                         f"| {d.delta_strict*100:+.1f}pp "
                         f"| {d.delta_loose*100:+.1f}pp "
                         f"| {d.note} |")
        lines.append("")
        lines.append("**复盘 checklist**：")
        lines.append('1. 对每条翻转配对，去 devlog / commit 里找当时报告的"成功结论"')
        lines.append("2. 判断是 (a) 评测集变可信导致旧结论作废 / (b) 评测集变错导致新结论假象")
        lines.append("3. 如是 (a)：把旧结论标记为 ❌ 假阳性，倒查决策链撤销影响")
        lines.append("4. 如是 (b)：补完评测集 + 重测")
    else:
        lines.append("✅ 无翻转 — 所有组合在历史评测集上的结论仍然成立。")
    lines.append("")
    lines.append("## 三、稳定配对（无翻转）")
    lines.append("")
    if not_flipped:
        for d in not_flipped[:10]:
            lines.append(f"- {d.combo} vs `{d.old_csv}`: "
                         f"Δ strict {d.delta_strict*100:+.1f}pp / "
                         f"Δ loose {d.delta_loose*100:+.1f}pp")
        if len(not_flipped) > 10:
            lines.append(f"- ... 还有 {len(not_flipped)-10} 条")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("**对应 AIPM v5.1 启示 39 + 第二十二章工程纪律**")

    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"📝 Markdown 报告: {md_path}")
    print(f"💾 JSON 报告:     {json_path}")
    print()
    if flipped:
        print(f"⚠️ {len(flipped)} 个翻转待复盘 — 详见报告")
    else:
        print("✅ 无翻转 — 历史结论全部稳定")


if __name__ == "__main__":
    main()

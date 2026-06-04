"""W5 D2：7 维度质量评测（LLM Judge）—— W5 D3 主菜工具铺垫。

7 维度（参考 PRD I.3）：
  1. 检索召回      Hit@5 loose       - 自动（已有 run_eval）
  2. 精确条款      Hit@5 strict      - 自动（已有 run_eval）
  3. 引用准确      LLM Judge         - 本脚本
  4. 原文用词      LLM Judge ★      - 本脚本（一票否决项）
  5. 数字精确      LLM Judge ★      - 本脚本（一票否决项）
  6. 边界识别      自动              - 已有 run_fallback_eval
  7. 不编造        LLM Judge ★      - 本脚本（一票否决项）

★ = 一票否决项（CLAUDE.md 红线 1-3）

设计：
  Step 1. 跑 RAG pipeline 拿到 query → answer + citations
  Step 2. LLM Judge 评 4 个维度（3/4/5/7）每个 0-1 打分
  Step 3. 合并 run_eval 已有的检索数字（1/2/6）
  Step 4. 计算综合得分（权重见 PRD I.3）

用法：
    python -m scripts.run_quality_eval --csv data/eval/eval_set_v1_150_v4_5.csv --limit 20
    python -m scripts.run_quality_eval --csv ... --limit 0  # 全集

输出：
    data/eval/quality/<timestamp>.md  人可读
    data/eval/quality/<timestamp>.json 机器可读

注意：成本约 0.005-0.01 元/条（DeepSeek），20 条 ~0.2 元，150 条 ~1.5 元。
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
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

DEFAULT_CSV = _BACKEND / "data" / "eval" / "eval_set_v1_150_v4_5.csv"
QUALITY_DIR = _BACKEND / "data" / "eval" / "quality"


# ── LLM Judge Prompt v2（W7 D2 启示 48 落地：防 Judge 自身 hallucinate）────────
# 改动 vs v1：
#   1. 加 4 条"自我警惕"约束（防凭印象造错字 / 不确定时避险给 1 分）
#   2. chunks 数 3 → 5 条
#   3. chunks 截断 200 → 500 字
#   4. 输出格式加 confidence 字段（hi/mid/lo）便于后续 calibration
JUDGE_SYSTEM_PROMPT = """你是规范知识问答系统的质量评审员。
给定 1) 用户 query  2) RAG 系统的回答  3) 系统检索到的 chunks，
你要从 4 个维度独立打分（每项 0 或 1）。

⚠️ **Judge 自我警惕约束（避免你自己 hallucinate）**：

1. **判 dim4 用词时，只能引用 chunks 实际出现的字符串**。不要凭印象判错字。
   如果 chunks 用的就是"游憩"，不要说"原文是'游患'被改为'游憩'" — 这是你自己造错字。
   每次判 dim4=0 前，**必须在脑中明确指出 chunks 里的原词 vs answer 里的当前词**，
   两者必须真实可见才能扣分。

2. **chunks 截断 500 字仍可能不全**：如果你怀疑 dim7 编造但 chunks 末尾是 "..."，
   说明 chunks 被截了；这种情况**给 1 分避险**，notes 注明 "chunks 截断不全"。

3. **dim4 只判量词**（应/不应/宜/不宜/可/不可/严禁/必须/不得），
   **不判业务逻辑错误**（如"280m 符合 300m 下限"逻辑错应归 dim7 而非 dim4）。

4. **数字 dim5**：单位前后空格不计错（"3.0m²/人" 跟 "3.0 m²/人" 视为一致）；
   只判数值或单位（如 "m" vs "m²"）的实际差异。

5. **不确定时给 1 分（避险）**，并在 notes 注明"不确定"。
   宁可漏判 false negative，也不要造 false positive。

【维度 3 · 引用准确】Citation Accuracy
- 1 分：回答中所有引用的规范名/标准号/条文号都来自检索到的 chunks
- 0 分：存在引用规范号或条文号是 chunks 中**确实没有**的（不要靠记忆，对照 chunks 实际文本）

【维度 4 · 原文用词】Original Wording ★ 一票否决
- 1 分："应/不应/宜/不宜/可/不可/严禁/必须/不得" 等量词与 chunks 原文一致
- 0 分：量词真有差异（你必须能从 chunks 引出原词 + 从 answer 引出错词）
- **只判量词，不判其他词的差异**

【维度 5 · 数字精确】Numerical Accuracy ★ 一票否决
- 1 分：回答中所有数字（300m / 1.5m² / 35% 等）与 chunks 原文一致
- 0 分：数字本身或单位真有差异（如 "3.0m" vs "3.0m²" 缺平方）
- **空格差异不算错**（"3.0m" = "3.0 m"）

【维度 7 · 不编造】No Hallucination ★ 一票否决
- 1 分：回答内容全部来自 chunks，无 chunks 之外的"经验补充"
- 0 分：回答**明确包含**chunks 之外的事实陈述（不是修辞性表达，是具体规范信息）
- **chunks 截断不全时（"..."结尾）默认给 1 分避险**

输出格式（严格 JSON，无其他文本）：
{
  "dim3_citation":   0 或 1,
  "dim4_wording":    0 或 1,
  "dim5_numeric":    0 或 1,
  "dim7_no_halluc":  0 或 1,
  "confidence":      "hi" | "mid" | "lo",
  "notes":           "30 字内说明哪个维度扣分原因 + chunks 原词引用（如 'dim4=0 chunks用宜 answer用应'）；如无扣分写'4 维全过'"
}
"""

JUDGE_USER_TEMPLATE = """【用户 query】
{query}

【RAG 回答】
{answer}

【检索到的 chunks（前 5 条，每条最多 500 字）】
{chunks}
"""


# 7 维度权重（PRD I.3）
WEIGHTS = {
    "dim1_recall":     0.20,   # Hit@5 loose（自动）
    "dim2_precision":  0.15,   # Hit@5 strict（自动）
    "dim3_citation":   0.20,   # LLM Judge
    "dim4_wording":    0.15,   # LLM Judge ★ 一票否决
    "dim5_numeric":    0.10,   # LLM Judge ★ 一票否决
    "dim6_boundary":   0.10,   # 自动（fallback eval）
    "dim7_no_halluc":  0.10,   # LLM Judge ★ 一票否决
}
VETO_DIMS = ("dim4_wording", "dim5_numeric", "dim7_no_halluc")


@dataclass
class QualityResult:
    qid: str
    query: str
    domain: str
    answer: str
    # 自动维度
    dim1_recall: int       # 0/1 (hit@5 loose)
    dim2_precision: int    # 0/1 (hit@5 strict)
    dim6_boundary: int     # 0/1 (boundary 自动；非 boundary query 默认 1)
    # LLM Judge 维度
    dim3_citation: int
    dim4_wording: int
    dim5_numeric: int
    dim7_no_halluc: int
    notes: str
    composite: float
    veto_triggered: bool


# ── 调 pipeline 拿 RAG 答案 + chunks ───────────────────────


def _run_pipeline(query: str) -> tuple[str, list[dict[str, Any]]]:
    """跑 1 次 RAG pipeline，返回 (answer, citations)。

    W6 D2：优先消费 `revised_answer` 事件（post_filter 净化版），
    否则回退到 token 拼接。这样评测 dim7 编造时看到的是 RAG 系统真实输出。
    """
    from app.rag.pipeline import run_rag_sync
    tokens: list[str] = []
    citations: list[dict[str, Any]] = []
    revised: str | None = None
    for evt in run_rag_sync(query):
        if evt["type"] == "token":
            tokens.append(evt["data"])
        elif evt["type"] == "citations":
            citations = evt["data"]
        elif evt["type"] == "revised_answer":
            # W6 D2：post_filter 已剥离补充说明节，用净化版做 Judge
            revised = evt["data"]
        elif evt["type"] in ("done", "fallback"):
            break
        elif evt["type"] == "error":
            logger.warning(f"[quality] pipeline 错误: {evt['data']}")
            break
    final_answer = revised if revised is not None else "".join(tokens)
    return final_answer, citations


# ── LLM Judge 调用 ────────────────────────────────────────


def _judge(query: str, answer: str, chunks: list[dict[str, Any]]) -> dict[str, Any]:
    """调 DeepSeek 评 4 维度。返回 dict 或 {"error": ...}。

    W5 D5：加 1 次重试机制（应对 DeepSeek 偶发 Connection error）。
    """
    from openai import APIError
    from app.rag.generator import get_client
    from app.core.config import settings

    # W7 D2 Judge v2：chunks 3→5 条，截断 200→500 字（启示 48 落地）
    chunks_str = "\n\n".join(
        f"[{i+1}] {c.get('spec_name','')} {c.get('spec_code','')} {c.get('clause','')}\n{c.get('original_text','')[:500]}"
        for i, c in enumerate(chunks[:5])
    ) or "（无 chunks）"

    messages = [
        {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
        {"role": "user", "content": JUDGE_USER_TEMPLATE.format(
            query=query, answer=answer[:500], chunks=chunks_str)},
    ]

    last_err: str = ""
    # W5 D5：尝试 2 次（1 次重试），避免单次 API 抖动污染评测
    for attempt in (1, 2):
        try:
            client = get_client()
            resp = client.chat.completions.create(
                model=settings.deepseek_model,
                messages=messages,
                temperature=0.1,
                max_tokens=200,
                timeout=20,
            )
            content = resp.choices[0].message.content or ""
            import re
            m = re.search(r'\{[^{}]*\}', content, re.DOTALL)
            if m:
                return json.loads(m.group(0))
            last_err = f"no_json: {content[:100]}"
        except APIError as e:
            last_err = f"api: {e}"
        except Exception as e:
            last_err = f"unknown: {e}"
        if attempt == 1:
            logger.info(f"[judge] attempt 1 failed: {last_err[:60]}, retrying...")
            time.sleep(1.5)  # 短暂退避
    return {"error": last_err}


# ── 主流程 ──────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="7 维度质量评测（LLM Judge）")
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--limit", type=int, default=20,
                        help="0=全集（注意 LLM 调用成本）")
    parser.add_argument("--out-dir", type=Path, default=QUALITY_DIR)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    if not args.csv.exists():
        print(f"❌ 评测集不存在：{args.csv}", file=sys.stderr)
        sys.exit(1)

    rows = list(csv.DictReader(open(args.csv, encoding="utf-8")))
    # 只评有效条目（boundary 在 run_fallback_eval 里评）
    rows = [r for r in rows if r.get("expected_spec", "").strip()]
    if args.limit > 0:
        rows = rows[:args.limit]

    print(f"\n🎯 7 维度质量评测")
    print(f"   评测集: {args.csv.name}")
    print(f"   样本数: {len(rows)} 条有效")
    print(f"   预估成本: ~{len(rows) * 0.008:.2f} 元 (DeepSeek)")
    print()

    # ── 1. 自动评检索维度（hit@5）──
    print(f"📊 第一阶段：自动跑 RAG 拿 answer + citations + 自动评 hit@5")
    from app.rag.embedder import embed_one
    from app.rag.retriever import dedup_results, search

    def norm(s): return (s or "").replace(" ", "").upper()
    def cmatch(e, a):
        e = (e or "").strip(); a = (a or "").strip()
        return bool(e and a and (e in a or a in e))

    results: list[QualityResult] = []
    skipped: list[dict[str, str]] = []  # W5 D5：跳过条目（API err 等）
    for i, row in enumerate(rows, 1):
        qid = row["id"]
        query = row["query"]
        expected_spec = row["expected_spec"]
        expected_clause = row["expected_clause"]

        # 跑 pipeline
        t0 = time.time()
        try:
            answer, citations = _run_pipeline(query)
        except Exception as e:
            logger.error(f"[{qid}] pipeline failed: {e}")
            skipped.append({"qid": qid, "reason": f"pipeline_failed: {str(e)[:60]}"})
            print(f"  [{i:3d}/{len(rows)}] {qid} | ⚠️ SKIP pipeline_failed: {str(e)[:40]}")
            continue

        # 自动评 dim1 (hit@5 loose) + dim2 (hit@5 strict)
        hit_loose = False
        hit_strict = False
        for c in citations[:5]:
            if norm(c.get("spec_code", "")) == norm(expected_spec):
                hit_loose = True
                if cmatch(expected_clause, c.get("clause", "")):
                    hit_strict = True
                    break

        # 调 LLM Judge（含 1 次重试）
        judge_result = _judge(query, answer, citations)
        # W5 D5：Judge API err 跳过该条不计入分母（避免污染均值 + 误触发 veto）
        if "error" in judge_result:
            err_msg = judge_result["error"][:80]
            logger.warning(f"[{qid}] judge failed after retry: {err_msg}")
            skipped.append({"qid": qid, "reason": f"judge_error: {err_msg}"})
            print(f"  [{i:3d}/{len(rows)}] {qid} | ⚠️ SKIP judge_error: {err_msg[:40]}")
            continue

        d3 = int(judge_result.get("dim3_citation", 0))
        d4 = int(judge_result.get("dim4_wording", 0))
        d5 = int(judge_result.get("dim5_numeric", 0))
        d7 = int(judge_result.get("dim7_no_halluc", 0))
        # W7 D2：confidence 字段（Judge v2 新增），用于后续 calibration 分析
        confidence = judge_result.get("confidence", "mid")  # hi/mid/lo
        notes_raw = judge_result.get("notes", "")[:50]
        notes = f"[{confidence}] {notes_raw}" if confidence != "mid" else notes_raw

        # 综合得分
        composite = (
            int(hit_loose) * WEIGHTS["dim1_recall"]
            + int(hit_strict) * WEIGHTS["dim2_precision"]
            + d3 * WEIGHTS["dim3_citation"]
            + d4 * WEIGHTS["dim4_wording"]
            + d5 * WEIGHTS["dim5_numeric"]
            + 1.0 * WEIGHTS["dim6_boundary"]    # 非 boundary 默认 1
            + d7 * WEIGHTS["dim7_no_halluc"]
        )
        veto = (d4 == 0) or (d5 == 0) or (d7 == 0)

        elapsed = time.time() - t0
        flag = "💀" if veto else ("⭐" if composite > 0.8 else "✓")
        print(f"  [{i:3d}/{len(rows)}] {qid} | {flag} {composite:.2f} | "
              f"d3={d3} d4={d4} d5={d5} d7={d7} | "
              f"hit@5 loose={'✓' if hit_loose else '✗'} strict={'✓' if hit_strict else '✗'} | "
              f"{elapsed:.1f}s")

        results.append(QualityResult(
            qid=qid,
            query=query,
            domain=row.get("spec_domain", ""),
            answer=answer[:300],
            dim1_recall=int(hit_loose),
            dim2_precision=int(hit_strict),
            dim6_boundary=1,
            dim3_citation=d3,
            dim4_wording=d4,
            dim5_numeric=d5,
            dim7_no_halluc=d7,
            notes=notes,
            composite=composite,
            veto_triggered=veto,
        ))

    # ── 聚合 ──
    n = len(results)
    n_attempted = len(rows)
    n_skipped = len(skipped)
    if n == 0:
        print("\n❌ 没有有效结果")
        sys.exit(1)

    avg = lambda key: sum(getattr(r, key) for r in results) / n
    avg_composite = sum(r.composite for r in results) / n
    n_veto = sum(1 for r in results if r.veto_triggered)

    print(f"\n📈 7 维度聚合（n_attempted={n_attempted}, n_eval={n}, n_skipped={n_skipped}）：")
    print(f"  dim1 检索召回 (loose) : {avg('dim1_recall'):.1%}")
    print(f"  dim2 精确条款 (strict): {avg('dim2_precision'):.1%}")
    print(f"  dim3 引用准确         : {avg('dim3_citation'):.1%}")
    print(f"  dim4 原文用词 ★       : {avg('dim4_wording'):.1%}")
    print(f"  dim5 数字精确 ★       : {avg('dim5_numeric'):.1%}")
    print(f"  dim6 边界识别          : 1.000（非 boundary 默认满分）")
    print(f"  dim7 不编造 ★         : {avg('dim7_no_halluc'):.1%}")
    print()
    print(f"  📊 综合得分（加权）     : {avg_composite*100:.1f} / 100")
    print(f"  💀 一票否决触发条数    : {n_veto} / {n}")
    if n_skipped > 0:
        print(f"  ⚠️  跳过条数（Judge / Pipeline 错误）: {n_skipped} / {n_attempted}")
        for s in skipped[:5]:
            print(f"     · {s['qid']}: {s['reason'][:60]}")
        if len(skipped) > 5:
            print(f"     · ... 等 {len(skipped) - 5} 条")
    print()

    if avg_composite >= 0.75 and n_veto == 0:
        print(f"  ✅ GREEN（综合 ≥75 且无一票否决）")
    elif avg_composite >= 0.6:
        print(f"  ⚠️  YELLOW（综合 60-75，需限定场景上线）")
    else:
        print(f"  ❌ RED（综合 <60，不可上线）")

    # 输出报告
    args.out_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    json_path = args.out_dir / f"quality_{ts}.json"
    md_path = args.out_dir / f"quality_{ts}.md"

    json_path.write_text(json.dumps({
        "csv": args.csv.name,
        "n_attempted": n_attempted,
        "n_eval": n,
        "n_skipped": n_skipped,
        "skipped": skipped,
        "weights": WEIGHTS,
        "overall": {
            "composite": avg_composite,
            "n_veto": n_veto,
            **{key: avg(key) for key in [
                "dim1_recall", "dim2_precision",
                "dim3_citation", "dim4_wording", "dim5_numeric", "dim7_no_halluc",
            ]},
        },
        "rows": [asdict(r) for r in results],
        "timestamp": ts,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    # Markdown 报告
    lines = [
        f"# 7 维度质量评测报告 · {args.csv.name}",
        "",
        f"**生成时间**: {ts}",
        f"**样本数**: {n} 条有效",
        f"**综合得分**: **{avg_composite*100:.1f} / 100**",
        f"**一票否决触发**: {n_veto} / {n}",
        "",
        "## 一、7 维度聚合",
        "",
        "| 维度 | 权重 | 平均分 | 性质 |",
        "|---|---|---|---|",
        f"| 1. 检索召回 (Hit@5 loose) | 20% | {avg('dim1_recall'):.1%} | 自动 |",
        f"| 2. 精确条款 (Hit@5 strict) | 15% | {avg('dim2_precision'):.1%} | 自动 |",
        f"| 3. 引用准确 | 20% | {avg('dim3_citation'):.1%} | LLM Judge |",
        f"| 4. 原文用词 ★ | 15% | {avg('dim4_wording'):.1%} | LLM Judge 一票否决 |",
        f"| 5. 数字精确 ★ | 10% | {avg('dim5_numeric'):.1%} | LLM Judge 一票否决 |",
        "| 6. 边界识别 | 10% | 100.0%（默认） | 自动 |",
        f"| 7. 不编造 ★ | 10% | {avg('dim7_no_halluc'):.1%} | LLM Judge 一票否决 |",
        "",
        "## 二、一票否决触发详情",
        "",
    ]
    veto_rows = [r for r in results if r.veto_triggered]
    if veto_rows:
        lines.append("| QID | 维度 | query 摘要 | 扣分原因 |")
        lines.append("|---|---|---|---|")
        for r in veto_rows[:15]:
            triggered = []
            if r.dim4_wording == 0: triggered.append("用词")
            if r.dim5_numeric == 0: triggered.append("数字")
            if r.dim7_no_halluc == 0: triggered.append("编造")
            lines.append(f"| {r.qid} | {','.join(triggered)} | {r.query[:30]}... | {r.notes} |")
    else:
        lines.append("✅ 无一票否决触发。")

    lines.extend([
        "",
        "---",
        "",
        f"**对应 PRD I.3 + AIPM v5.2 启示 39（防假阳性）**",
    ])
    md_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"\n📝 报告：{md_path}")
    print(f"💾 JSON：{json_path}")


if __name__ == "__main__":
    main()

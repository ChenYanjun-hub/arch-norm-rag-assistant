"""W5 D3：从 quality_eval 全量结果中分层抽样 30 条，
导出为人可读 markdown 用于核对 LLM Judge 准确性。

抽样策略：
  - 一票否决触发的全抽（最多 15 条）
  - 非触发的随机抽到 30 条上限
  - 同时打印对应的检索 chunks（前 3 条）+ RAG 回答

用法：
    python -m scripts.sample_quality_review --json data/eval/quality/quality_<ts>.json --n 30

输出：
    data/eval/quality/sample_review_<ts>.md  人可读

注意：
  - 不调 LLM，纯本地分析
  - chunks 内容会重新跑一次 RAG（拿 citations）
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", type=Path, required=True,
                        help="quality_eval 输出的 JSON 路径")
    parser.add_argument("--csv", type=Path,
                        default=_BACKEND / "data" / "eval" / "eval_set_v1_150_v4_5.csv")
    parser.add_argument("--n", type=int, default=30,
                        help="目标抽样数")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    if not args.json.exists():
        print(f"❌ JSON 不存在：{args.json}", file=sys.stderr)
        sys.exit(1)

    data = json.loads(args.json.read_text(encoding="utf-8"))
    rows = data["rows"]

    # 评测集 csv（取 expected_answer 用于核对）
    csv_map = {}
    if args.csv.exists():
        with open(args.csv, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                csv_map[r["id"]] = r

    # 分层抽样：veto 全要 + 非 veto 随机补
    veto_rows = [r for r in rows if r.get("veto_triggered")]
    non_veto_rows = [r for r in rows if not r.get("veto_triggered")]

    random.seed(args.seed)
    veto_sample = veto_rows[:min(15, len(veto_rows))]
    remaining = args.n - len(veto_sample)
    non_veto_sample = random.sample(non_veto_rows, min(remaining, len(non_veto_rows)))
    sample = veto_sample + non_veto_sample

    print(f"\n📊 抽样：veto {len(veto_sample)} + non_veto {len(non_veto_sample)} = {len(sample)} 条")

    # ── 输出 markdown ──
    out_dir = args.json.parent
    ts = args.json.stem.replace("quality_", "")
    md_path = out_dir / f"sample_review_{ts}.md"

    lines = [
        f"# Quality Judge 核对样本 · {len(sample)} 条",
        "",
        f"**抽样来源**：{args.json.name}",
        f"**抽样策略**：veto 全要 ({len(veto_sample)}) + 非 veto 随机 ({len(non_veto_sample)})",
        f"**用途**：对照 chunks 真实内容，核对 LLM Judge 在 dim3/4/5/7 的判断",
        "",
        "## 核对原则",
        "",
        "- **dim3 引用**：回答的规范号 + 条文号 是否都来自 chunks",
        "- **dim4 用词**：应/不应/宜/不宜 等是否与原文一致",
        "- **dim5 数字**：数字（米、米²、%、人数）是否与原文 1 字不差",
        "- **dim7 编造**：是否包含 chunks 之外的内容",
        "",
        "---",
        "",
    ]

    for i, r in enumerate(sample, 1):
        qid = r["qid"]
        csv_r = csv_map.get(qid, {})
        flag = "💀 VETO" if r.get("veto_triggered") else "✓"

        lines.extend([
            f"## [{i:2d}/{len(sample)}] {qid} · {flag} · composite={r['composite']:.2f}",
            "",
            f"**Query**：{r['query']}",
            f"**期望 spec**：{csv_r.get('expected_spec', '?')} · "
            f"**期望 clause**：{csv_r.get('expected_clause', '?')}",
            f"**期望 expected_answer**：{csv_r.get('expected_answer', '')[:120]}",
            "",
            "### Judge 打分",
            "",
            f"- dim1 hit@5 loose: {r['dim1_recall']}",
            f"- dim2 hit@5 strict: {r['dim2_precision']}",
            f"- dim3 引用准确: {r['dim3_citation']}",
            f"- dim4 原文用词 ★: {r['dim4_wording']}",
            f"- dim5 数字精确 ★: {r['dim5_numeric']}",
            f"- dim7 不编造 ★: {r['dim7_no_halluc']}",
            f"- **Judge notes**: {r.get('notes', '')}",
            "",
            "### RAG 回答（前 300 字）",
            "",
            "```",
            r.get("answer", "")[:300],
            "```",
            "",
            "### 我的人工评分（请填）",
            "",
            "- dim3 引用准确: [ ] 1 / [ ] 0 — 备注：",
            "- dim4 原文用词: [ ] 1 / [ ] 0 — 备注：",
            "- dim5 数字精确: [ ] 1 / [ ] 0 — 备注：",
            "- dim7 不编造: [ ] 1 / [ ] 0 — 备注：",
            "",
            "**Judge 是否准确？** [ ] 完全 / [ ] 偏严 / [ ] 偏松 / [ ] 错判",
            "",
            "---",
            "",
        ])

    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"📝 输出：{md_path}")
    print(f"💡 阅读后在文件里勾选 + 备注，统计 LLM Judge 准确率。")


if __name__ == "__main__":
    main()

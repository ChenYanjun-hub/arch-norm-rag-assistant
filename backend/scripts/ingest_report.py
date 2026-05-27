"""读取 chunks/_ingest_report.json，生成可读的汇总报告。

用法：
    cd backend
    .venv/bin/python -m scripts.ingest_report
    .venv/bin/python -m scripts.ingest_report --out docs/devlog/ingest_report.md
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402

REPORT_PATH = Path(settings.chunks_dir) / "_ingest_report.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", help="输出 markdown 文件路径（默认打印到 stdout）")
    args = parser.parse_args()

    if not REPORT_PATH.exists():
        print(f"❌ 报告不存在: {REPORT_PATH}", file=sys.stderr)
        return 2

    with REPORT_PATH.open() as f:
        data = json.load(f)

    details = data["details"]
    # 三类项：成功（有 chunks_total）/ 异常报错（有 error）/ 0 chunks（既无 error 也无 chunks_total）
    success = [d for d in details if "chunks_total" in d]
    failed = [d for d in details if "error" in d]
    empty = [d for d in details if "chunks_total" not in d and "error" not in d]

    total_chunks = sum(d["chunks_total"] for d in success)
    total_mandatory = sum(d["mandatory_count"] for d in success)
    by_domain = Counter(d["domain"] for d in success)
    chunks_by_domain: dict[str, int] = {}
    for d in success:
        chunks_by_domain[d["domain"]] = chunks_by_domain.get(d["domain"], 0) + d["chunks_total"]

    total_elapsed = sum(d.get("elapsed_s", 0) for d in success)

    by_type_total: Counter[str] = Counter()
    for d in success:
        for k, v in d.get("by_type", {}).items():
            by_type_total[k] += v

    lines: list[str] = []
    lines.append("# 全量 ingest 报告")
    lines.append("")
    lines.append(f"- 总 PDF 数：{data['total_files']}")
    lines.append(f"- 成功（产出 chunks）：{len(success)}")
    lines.append(f"- 0 chunks（chunker 未识别出条文）：{len(empty)}")
    lines.append(f"- 异常报错：{len(failed)}")
    lines.append(f"- 总 chunks 数：**{total_chunks}**")
    lines.append(f"- 总强制性条文：**{total_mandatory}**（占 {total_mandatory/total_chunks:.1%}）")
    lines.append(f"- 总耗时：{total_elapsed:.1f}s · 平均每部 {total_elapsed/max(len(success),1):.1f}s")
    lines.append("")
    lines.append("## chunk 类型分布")
    lines.append("")
    lines.append("| type | 数量 | 占比 |")
    lines.append("|---|---|---|")
    for t in ("clause", "table", "formula", "appendix"):
        cnt = by_type_total.get(t, 0)
        lines.append(f"| {t} | {cnt} | {cnt/total_chunks:.1%} |")
    lines.append("")

    lines.append("## domain 分布")
    lines.append("")
    lines.append("| domain | PDF 数 | chunks 数 | 平均/部 |")
    lines.append("|---|---|---|---|")
    for dom in ("规划", "建筑", "景观", "消防"):
        n_pdf = by_domain.get(dom, 0)
        n_chunks = chunks_by_domain.get(dom, 0)
        avg = n_chunks / n_pdf if n_pdf else 0
        lines.append(f"| {dom} | {n_pdf} | {n_chunks} | {avg:.0f} |")
    lines.append("")

    lines.append("## 单部 PDF 明细（按 chunks 数降序）")
    lines.append("")
    lines.append("| 规范号 | domain | chunks | mandatory | chunk耗时 | embed耗时 |")
    lines.append("|---|---|---|---|---|---|")
    for d in sorted(success, key=lambda x: -x["chunks_total"]):
        lines.append(
            f"| {d['spec_code']} | {d['domain']} | {d['chunks_total']} | "
            f"{d['mandatory_count']} | "
            f"{d.get('chunk_seconds', 0):.1f}s | {d.get('embed_seconds', 0):.1f}s |"
        )
    lines.append("")

    if failed:
        lines.append("## ⚠️ 异常报错清单")
        lines.append("")
        for d in failed:
            lines.append(f"- `{d['file']}` — {d['error']}")
        lines.append("")

    if empty:
        lines.append("## ⚠️ 0 chunks 清单（chunker 未识别出条文）")
        lines.append("")
        for d in empty:
            lines.append(f"- `{d['file']}` — 耗时 {d.get('elapsed_s', 0):.1f}s")
        lines.append("")

    # 极值
    if success:
        sizes = [(d["spec_code"], d["chunks_total"]) for d in success]
        sizes.sort(key=lambda x: x[1])
        lines.append("## 极值观察")
        lines.append("")
        lines.append(f"- chunks 最少：{sizes[0][0]} → {sizes[0][1]} 个")
        lines.append(f"- chunks 最多：{sizes[-1][0]} → {sizes[-1][1]} 个")
        lines.append("")

    out_text = "\n".join(lines)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(out_text, encoding="utf-8")
        print(f"✅ 报告写入：{out_path}")
    else:
        print(out_text)
    return 0


if __name__ == "__main__":
    sys.exit(main())

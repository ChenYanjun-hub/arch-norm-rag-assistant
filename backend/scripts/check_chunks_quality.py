"""W6 D0：chunks OCR 校对工具（启示 49 落地）。

背景：W5 D3-D5 元评测发现 chunks 里的 PDF OCR 错字会污染 LLM Judge 判断：
  - Q090 "定牌" — chunks 中 OCR 把某词识别成"定牌"
  - Q084 "路同密度" — Judge 凭印象造的错字模式
  - CJJT_75 第 1 个 chunk："改著贼市" / "坏境" / "政计" — 多处错字

本工具：
  - 扫描 data/chunks/*.json
  - 启发式检测可疑 OCR 错字
  - 输出可疑 chunks 列表，供人工/LLM 复核

不修复策略由用户选（见 docs/W6_plan.md P0-2）：
  A 人工抽样修复  B LLM 自校对  C 重 OCR  D 仅标记 ocr_quality=low

用法：
    python -m scripts.check_chunks_quality                       # 扫全部
    python -m scripts.check_chunks_quality --spec CJJT_75        # 仅扫指定规范
    python -m scripts.check_chunks_quality --out report.md       # 输出 markdown

输出（默认）：
    backend/data/chunks_quality/report_<ts>.md
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
CHUNKS_DIR = _BACKEND / "data" / "chunks"
DEFAULT_OUT = _BACKEND / "data" / "chunks_quality"


# ── 已知 OCR 错字字典（W5 D3-D5 沉淀，会随 W6+ 持续扩充）──
# 格式：错字 → 可能正字（或多候选）
KNOWN_OCR_ERRORS = {
    # CJJT_75 第 1 个 chunk 看到的
    "贼市": "城市",
    "改著": "改善",
    "坏境": "环境",
    "政计": "设计",
    # W5 D4 Q090 实际 chunk 里的（"定牌"暂存观察）
    "定牌": "（待人工确认）",
    # 常见 OCR 字混淆（部首相似）
    "白勺": "的",
    "扦": "并",  # 中文常见误识
}


# ── 启发式规则 ─────────────────────────────────────────


def _suspicious_chars(text: str) -> list[str]:
    """检测明显异常的 unicode 字符（罕见字 + 不合常理的混排）。"""
    issues: list[str] = []
    # 不在常用汉字 + 标点范围
    for ch in text:
        if ch.isascii():
            continue
        cp = ord(ch)
        # 排除常用汉字 (U+4E00-U+9FFF) + 中文标点 (U+3000-U+303F, U+FF00-U+FFEF)
        # + 一般标点 (U+2010-U+2027 含引号 省略号 破折号) + 千分号等
        if 0x4E00 <= cp <= 0x9FFF:
            continue
        if 0x3000 <= cp <= 0x303F or 0xFF00 <= cp <= 0xFFEF:
            continue
        if 0x2010 <= cp <= 0x2030:  # 引号 / 破折号 / 省略号 / 千分号
            continue
        if ch in "·°¥™©®§¶":
            continue
        # 工程符号（角度 / 数学 / 物理常用，规范文本常见）
        if ch in "∠×÷±√≤≥≠≈∞∑∏∫∂μνωΩαβγδεθλπρστφχψ":
            continue
        if 0x0391 <= cp <= 0x03C9:  # 希腊字母
            continue
        # 其他罕见 unicode 才报
        issues.append(f"unicode 罕见: {ch} (U+{cp:04X})")
    return issues


def _known_errors(text: str) -> list[str]:
    """匹配已知 OCR 错字字典。"""
    issues: list[str] = []
    for err, fix in KNOWN_OCR_ERRORS.items():
        if err in text:
            issues.append(f"已知错字: '{err}' → '{fix}'")
    return issues


def _consecutive_punct(text: str) -> list[str]:
    """检测连续标点（OCR 经常把字识别成标点）。"""
    issues: list[str] = []
    m = re.search(r'([。，；：、，,;:])\1{2,}', text)
    if m:
        issues.append(f"连续标点: '{m.group(0)}'")
    return issues


def _malformed_numbers(text: str) -> list[str]:
    """检测异常数字（如 "1〇" 或 "lOOm" 的 l/O 混淆）。"""
    issues: list[str] = []
    # 数字 + 全角圆圈
    if re.search(r'\d[〇○]', text):
        issues.append("可疑数字: '数字+〇/○' 混淆")
    # l/I 后紧跟单位（m / cm / km / mm / hm 等）才报 — 强限定避免误报正常英文 ID
    if re.search(r'(?<![a-zA-Z])[lI](?=\d*(?:cm|mm|km|hm|m[²³]?\b|度|°))', text):
        issues.append("可疑数字: 'l/I' 误为 '1'")
    return issues


def _abnormal_unicode_runs(text: str) -> list[str]:
    """检测异常长的非汉字非标点字符串（OCR 失败痕迹）。"""
    issues: list[str] = []
    # 连续 3+ 个英文字母夹在中文里 — 多数是 OCR 错
    if re.search(r'[一-鿿]{2,}[a-zA-Z]{3,}[一-鿿]{2,}', text):
        issues.append("可疑混排: 中文中嵌入 3+ 英文字母")
    return issues


HEURISTICS = [
    ("known_errors", _known_errors),
    ("consecutive_punct", _consecutive_punct),
    ("malformed_numbers", _malformed_numbers),
    ("abnormal_unicode_runs", _abnormal_unicode_runs),
    ("suspicious_chars", _suspicious_chars),
]


# ── 结果数据结构 ────────────────────────────────────────


@dataclass
class ChunkIssue:
    chunk_id: str
    spec_code: str
    clause: str
    text_preview: str
    issues: list[str] = field(default_factory=list)


# ── 主流程 ─────────────────────────────────────────────


def scan_chunks(chunks_dir: Path, spec_filter: str | None = None) -> list[ChunkIssue]:
    """扫描所有 chunks，返回可疑列表。"""
    results: list[ChunkIssue] = []
    json_files = sorted(chunks_dir.glob("*.json"))
    if spec_filter:
        json_files = [f for f in json_files if spec_filter in f.name]

    for jf in json_files:
        if jf.name.startswith("_"):  # 跳过 _ingest_report.json 等非 chunks 文件
            continue
        data = json.loads(jf.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            continue
        for ck in data:
            if not isinstance(ck, dict):
                continue
            text = ck.get("text", "")
            if not text:
                continue
            chunk_issues: list[str] = []
            for name, fn in HEURISTICS:
                hits = fn(text)
                chunk_issues.extend(hits)
            if chunk_issues:
                preview = text.replace("\n", " ")[:80]
                results.append(ChunkIssue(
                    chunk_id=ck.get("chunk_id", "?"),
                    spec_code=ck.get("spec_code", "?"),
                    clause=ck.get("clause", "?"),
                    text_preview=preview,
                    issues=chunk_issues,
                ))
    return results


def write_report(results: list[ChunkIssue], out_path: Path) -> None:
    """写 markdown 报告。"""
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # 按 issue 类型统计
    issue_counter: Counter[str] = Counter()
    for r in results:
        for issue in r.issues:
            kind = issue.split(":")[0]
            issue_counter[kind] += 1

    spec_counter: Counter[str] = Counter()
    for r in results:
        spec_counter[r.spec_code] += 1

    lines = [
        f"# Chunks 质量扫描报告",
        "",
        f"**扫描时间**: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"**可疑 chunks 总数**: {len(results)}",
        "",
        "## 一、按问题类型统计",
        "",
        "| 类型 | 数量 |",
        "|---|---|",
    ]
    for kind, n in issue_counter.most_common():
        lines.append(f"| {kind} | {n} |")

    lines.extend([
        "",
        "## 二、按规范分布",
        "",
        "| 规范 | 可疑 chunks 数 |",
        "|---|---|",
    ])
    for spec, n in spec_counter.most_common(15):
        lines.append(f"| {spec} | {n} |")

    lines.extend([
        "",
        "## 三、可疑 chunks 详情（前 50 条）",
        "",
        "| QID | spec | clause | 问题 | 文本片段 |",
        "|---|---|---|---|---|",
    ])
    for r in results[:50]:
        issues_str = "<br>".join(r.issues[:3])
        if len(r.issues) > 3:
            issues_str += f"<br>... 等 {len(r.issues)} 类"
        lines.append(f"| {r.chunk_id} | {r.spec_code} | {r.clause} | {issues_str} | {r.text_preview} |")

    if len(results) > 50:
        lines.append(f"\n*... 还有 {len(results) - 50} 条未列出，详见 JSON*")

    lines.extend([
        "",
        "---",
        "",
        "**修复策略**（待用户决策，见 docs/W6_plan.md P0-2）：",
        "- A 人工抽样修复",
        "- B LLM 自校对",
        "- C 重新 OCR",
        "- D 仅标记 ocr_quality=low（不修复，让下游知道）",
    ])

    out_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", help="仅扫指定规范（如 CJJT_75）")
    parser.add_argument("--out", type=Path,
                        help="输出 markdown 路径（默认 data/chunks_quality/report_<ts>.md）")
    parser.add_argument("--chunks-dir", type=Path, default=CHUNKS_DIR)
    args = parser.parse_args()

    if not args.chunks_dir.exists():
        print(f"❌ chunks 目录不存在：{args.chunks_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"🔍 扫描 {args.chunks_dir}（spec={args.spec or '全部'}）...")
    results = scan_chunks(args.chunks_dir, args.spec)

    ts = time.strftime("%Y%m%d_%H%M%S")
    out_path = args.out or (DEFAULT_OUT / f"report_{ts}.md")
    write_report(results, out_path)

    json_path = out_path.with_suffix(".json")
    json_path.write_text(json.dumps(
        [{
            "chunk_id": r.chunk_id, "spec_code": r.spec_code,
            "clause": r.clause, "text_preview": r.text_preview,
            "issues": r.issues,
        } for r in results],
        ensure_ascii=False, indent=2,
    ), encoding="utf-8")

    # ── 总结 ──
    print(f"\n📊 可疑 chunks: {len(results)} 条")
    print(f"📝 报告: {out_path}")
    print(f"💾 JSON: {json_path}")
    if results:
        print(f"\n前 5 条示例:")
        for r in results[:5]:
            print(f"  · {r.chunk_id} ({r.spec_code} {r.clause}): {r.issues[0]}")


if __name__ == "__main__":
    main()

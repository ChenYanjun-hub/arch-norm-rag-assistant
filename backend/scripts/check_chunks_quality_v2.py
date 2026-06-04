"""W7 D3：chunks 二轮 LLM OCR 校对工具（启示 64 落地）。

W6 D0 v1（check_chunks_quality.py）：启发式扫已知错字字典 → 28 处真错 + 几千条误报
W7 D3 v2：两阶段方案降成本
    阶段 1：扩展启发式扫 "高度可疑模式"（漏单位 / 错字邻接 / OCR 常见误识）
            → 缩小到 ~300-500 条高度可疑 chunks
    阶段 2：用 DeepSeek 对这些 chunks 做"是否需要修复"判断 + 给修复建议
            → 输出可疑列表 + 上下文 + 建议（仅扫描，不改原文件）

启示 49 / 64 落地。

成本预估：
    阶段 1：免费（纯本地扫描）
    阶段 2：~300-500 chunks × ~200 tokens 输入 = ~80K tokens ≈ 0.5 元 DeepSeek

用法：
    python -m scripts.check_chunks_quality_v2 --dry-run    # 仅阶段 1（默认）
    python -m scripts.check_chunks_quality_v2 --llm        # 阶段 1 + 2 LLM 校对
    python -m scripts.check_chunks_quality_v2 --llm --spec CJJT_75  # 单 spec 测试

输出：
    backend/data/chunks_quality/v2_report_<ts>.md  人可读
    backend/data/chunks_quality/v2_report_<ts>.json  机器可读
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
sys.path.insert(0, str(_BACKEND))

CHUNKS_DIR = _BACKEND / "data" / "chunks"
DEFAULT_OUT = _BACKEND / "data" / "chunks_quality"


# ── 阶段 1：扩展启发式（在 v1 基础上加更多 W7 D2 发现的模式）──

# v1 已有的已知错字字典（W6 D0 沉淀）
KNOWN_OCR_ERRORS_V1 = {
    "贼市": "城市",
    "改著": "改善",
    "坏境": "环境",
    "政计": "设计",
    "保沪": "保护",
}

# W7 D2 新发现的错字模式（启示 64）
KNOWN_OCR_ERRORS_V2 = {
    "游患": "游憩",
    "不应低丁": "不应低于",
    "路同密度": "路网密度",
    "宜案用": "宜采用",
    "完著": "完善",
    "数他": "设施",
    "店任": "居住",
    "贼市": "城市",
    "8.0m7人": "8.0m²/人",
}

# 合并字典
ALL_KNOWN_ERRORS = {**KNOWN_OCR_ERRORS_V1, **KNOWN_OCR_ERRORS_V2}

# 单位漏字模式（数字后跟单位，但可能漏了"²"）
# 如 "0.50m/人" 应该是 "0.50m²/人"
# 但要小心不误报真单位（如 "200m" 表示长度时不漏单位）
_UNIT_DROP_PATTERNS = [
    # 数字 + m/人 → 可能漏 "²"
    (re.compile(r"(\d+\.?\d*)\s*m\s*/\s*人"), r"\1m²/人"),
    # 数字 + m/床 → 可能漏 "²"
    (re.compile(r"(\d+\.?\d*)\s*m\s*/\s*床"), r"\1m²/床"),
    # 数字 + m/生 → 可能漏 "²"
    (re.compile(r"(\d+\.?\d*)\s*m\s*/\s*生"), r"\1m²/生"),
    # 数字 + m/张 → 可能漏 "²"
    (re.compile(r"(\d+\.?\d*)\s*m\s*/\s*张"), r"\1m²/张"),
    # 每 数字m + 绿地/座位/标台 等 → 可能漏 "²"
    (re.compile(r"每\s*(\d+)\s*m\s*(绿地|座位|标台|个|户)"), r"每\1m²\2"),
]

# 数字 + 字母错位（如 "8.0m7人" 中 "7" 是错字，应是 "²/"）
_NUMBER_LETTER_PATTERN = re.compile(r"\d+(\.\d+)?\s*m\s*\d")

# OCR 常见错字字符（孤立出现时高度可疑）
SUSPICIOUS_CHARS = {
    "丁": "于",   # 错"于"为"丁"
    "灭": "大",   # "不应灭于" → "不应大于"
    "卷": "者",
    "胃": "置",
}


@dataclass
class SuspiciousChunk:
    chunk_id: str
    spec_code: str
    clause: str
    text: str
    issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    confidence: str = "mid"  # hi / mid / lo
    llm_verdict: str = ""    # LLM 校对结果（阶段 2 填）


def _scan_stage_1(chunks_dir: Path, spec_filter: str | None = None) -> list[SuspiciousChunk]:
    """阶段 1 启发式扫描，返回高度可疑 chunks。"""
    results: list[SuspiciousChunk] = []
    json_files = sorted(chunks_dir.glob("*.json"))
    if spec_filter:
        json_files = [f for f in json_files if spec_filter in f.name]

    for jf in json_files:
        if jf.name.startswith("_"):
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

            issues: list[str] = []
            suggestions: list[str] = []

            # 1. 已知错字字典
            for err, fix in ALL_KNOWN_ERRORS.items():
                if err in text:
                    issues.append(f"known: '{err}' → '{fix}'")
                    suggestions.append(text.replace(err, fix))

            # 2. 单位漏字
            for pat, fix_template in _UNIT_DROP_PATTERNS:
                if pat.search(text):
                    m = pat.search(text)
                    issues.append(f"unit_drop: '{m.group(0)}' 可能漏 '²'")
                    suggested = pat.sub(fix_template, text)
                    if suggested != text:
                        suggestions.append(suggested)

            # 3. 数字+字母错位（"8.0m7人"）
            for m in _NUMBER_LETTER_PATTERN.finditer(text):
                issues.append(f"number_letter_mix: '{m.group(0)}' 字母后跟数字可疑")

            # 4. 单独可疑字符（如 "不应低丁"）
            for ch, fix in SUSPICIOUS_CHARS.items():
                # 只报"不应低丁"/"不应灭于"这种规范上下文，避免误报
                contexts = [f"低{ch}", f"灭{ch}", f"{ch}于", f"{ch}市"]
                for pattern in contexts:
                    if pattern in text:
                        issues.append(f"suspicious_char: '{pattern}' (可能错字 → '{ch}→{fix}')")

            if issues:
                # confidence 估算：已知字典命中=hi，模式匹配=mid
                confidence = "hi" if any("known:" in i for i in issues) else "mid"
                results.append(SuspiciousChunk(
                    chunk_id=ck.get("chunk_id", "?"),
                    spec_code=ck.get("spec_code", "?"),
                    clause=ck.get("clause", "?"),
                    text=text,
                    issues=issues,
                    suggestions=suggestions,
                    confidence=confidence,
                ))
    return results


def _llm_verify(suspicious: list[SuspiciousChunk]) -> None:
    """阶段 2：用 DeepSeek 对高度可疑 chunks 做最终判断（修改 in-place 加 llm_verdict）。"""
    from app.rag.generator import get_client
    from app.core.config import settings

    SYSTEM_PROMPT = """你是规范文本 OCR 校对助手。
给定一段从 PDF OCR 出来的规范条文 text 和系统启发式扫描的可疑点 issues，
你的任务：

1. 判断这些 issues 中哪些是真错字（需要修），哪些是误报（正常字符被误判）
2. 输出**严格 JSON**（无其他文本）：

{
  "true_errors": ["错字1", "错字2"],   // 真需要修的错字（chunks 里的）
  "fix_suggestions": {"错字": "正字"},  // 修复建议字典
  "verdict": "needs_fix" | "false_positive" | "uncertain",
  "notes": "20 字内说明"
}

注意：
- 只判 chunks 本身的字符错误（OCR 误识 / 漏字），不判语义
- 如不确定，verdict="uncertain"，true_errors 保守只列高把握的
"""

    client = get_client()
    for i, s in enumerate(suspicious):
        if (i + 1) % 20 == 0:
            print(f"  LLM 校对进度 {i+1}/{len(suspicious)}...")

        user_msg = f"""【chunks text】
{s.text[:500]}

【启发式扫描可疑点】
{chr(10).join('- ' + iss for iss in s.issues)}

请校对并输出 JSON。"""

        try:
            resp = client.chat.completions.create(
                model=settings.deepseek_model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.1,
                max_tokens=200,
                timeout=20,
            )
            content = resp.choices[0].message.content or ""
            m = re.search(r'\{[^{}]*\}', content, re.DOTALL)
            if m:
                parsed = json.loads(m.group(0))
                verdict = parsed.get("verdict", "uncertain")
                notes = parsed.get("notes", "")[:50]
                true_errors = parsed.get("true_errors", [])
                s.llm_verdict = f"[{verdict}] true={true_errors} | {notes}"
            else:
                s.llm_verdict = f"[parse_err] {content[:60]}"
        except Exception as e:
            s.llm_verdict = f"[api_err] {str(e)[:40]}"


def _write_report(results: list[SuspiciousChunk], out_dir: Path, llm_done: bool) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    md_path = out_dir / f"v2_report_{ts}.md"
    json_path = out_dir / f"v2_report_{ts}.json"

    # 按 confidence + LLM verdict 分类
    if llm_done:
        true_fix = [r for r in results if r.llm_verdict.startswith("[needs_fix]")]
        false_pos = [r for r in results if r.llm_verdict.startswith("[false_positive]")]
        uncertain = [r for r in results if r.llm_verdict.startswith("[uncertain]") or "parse_err" in r.llm_verdict or "api_err" in r.llm_verdict]
    else:
        # 仅阶段 1
        true_fix = [r for r in results if r.confidence == "hi"]
        false_pos = []
        uncertain = [r for r in results if r.confidence != "hi"]

    issue_counter: Counter[str] = Counter()
    for r in results:
        for iss in r.issues:
            kind = iss.split(":")[0]
            issue_counter[kind] += 1

    lines = [
        f"# Chunks 质量扫描报告 v2（W7 D3）",
        "",
        f"**生成时间**: {ts}",
        f"**扫描模式**: {'阶段 1 启发式 + 阶段 2 LLM 校对' if llm_done else '仅阶段 1 启发式（用 --llm 跑阶段 2）'}",
        f"**可疑 chunks 总数**: {len(results)}",
        "",
        "## 一、分类结果",
        "",
        f"- ✅ 高把握需修复（LLM verdict=needs_fix 或启发式 hi）: **{len(true_fix)} 条**",
        f"- ❌ LLM 判定误报: {len(false_pos)} 条",
        f"- ⚠️ 不确定: {len(uncertain)} 条",
        "",
        "## 二、按问题类型统计",
        "",
        "| 类型 | 数量 |",
        "|---|---|",
    ]
    for k, n in issue_counter.most_common():
        lines.append(f"| {k} | {n} |")

    lines.extend(["", "## 三、需修复的 chunks 详情（前 50 条）", ""])
    lines.append("| QID | spec | clause | issues | LLM 判定 | suggested fix |")
    lines.append("|---|---|---|---|---|---|")
    for r in true_fix[:50]:
        issues_str = "<br>".join(r.issues[:2])
        suggest = r.suggestions[0][:60] + "..." if r.suggestions else ""
        verdict = r.llm_verdict[:60] if r.llm_verdict else "(无 LLM 校对)"
        lines.append(f"| {r.chunk_id} | {r.spec_code} | {r.clause} | {issues_str} | {verdict} | {suggest} |")

    if len(true_fix) > 50:
        lines.append(f"\n*... 还有 {len(true_fix) - 50} 条，详见 JSON*")

    lines.extend([
        "",
        "## 四、修复建议（W7 D3-3 用户决策）",
        "",
        "- A: 修全部 LLM verdict=needs_fix（高把握）",
        "- B: 修启发式 confidence=hi + LLM 二次确认（最稳）",
        "- C: 不修，仅记录 ocr_quality 元数据（最保守）",
    ])

    md_path.write_text("\n".join(lines), encoding="utf-8")

    json_data = [
        {
            "chunk_id": r.chunk_id,
            "spec_code": r.spec_code,
            "clause": r.clause,
            "text_preview": r.text[:200],
            "issues": r.issues,
            "suggestions": r.suggestions,
            "confidence": r.confidence,
            "llm_verdict": r.llm_verdict,
        }
        for r in results
    ]
    json_path.write_text(json.dumps(json_data, ensure_ascii=False, indent=2), encoding="utf-8")

    return md_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", help="仅扫指定规范")
    parser.add_argument("--llm", action="store_true", help="启用阶段 2 LLM 校对")
    parser.add_argument("--chunks-dir", type=Path, default=CHUNKS_DIR)
    args = parser.parse_args()

    print(f"🔍 阶段 1：启发式扫描 {args.chunks_dir}（spec={args.spec or '全部'}）...")
    results = _scan_stage_1(args.chunks_dir, args.spec)
    print(f"   阶段 1 完成：{len(results)} 条可疑")
    print(f"   - 启发式 hi（已知错字）: {sum(1 for r in results if r.confidence=='hi')}")
    print(f"   - 启发式 mid（模式匹配）: {sum(1 for r in results if r.confidence=='mid')}")

    if args.llm:
        # 估算成本
        n = len(results)
        est_tokens = n * 250  # 平均 250 token/条 (input + output)
        est_cost = est_tokens / 1_000_000 * 2  # DeepSeek ~2 元/1M tokens
        print(f"\n💰 阶段 2 LLM 校对成本预估：{n} 条 × 250 tokens ≈ {est_cost:.2f} 元")
        print(f"   阶段 2 开始 LLM 校对...")
        _llm_verify(results)

    md_path = _write_report(results, DEFAULT_OUT, llm_done=args.llm)
    print(f"\n📝 报告：{md_path}")
    if not args.llm:
        print(f"💡 加 --llm 参数跑阶段 2 LLM 校对（用 DeepSeek 二次确认）")


if __name__ == "__main__":
    main()

"""批量修 chunks 里的 OCR 系统性错字（启示 49/64 落地修复）。

两类修复：
  1. FIX_MAP 精确错字替换（W5 D5 → W7 D4 累积，每条人工 review 上下文无歧义）
  2. fix_units 正则修复人均面积单位里被 OCR 丢失/误识的上标 ²（W7 D4 新增）

W7 D4 新增（启示 64 继续落地 — 直接对应 Q102/Q003 真顽疾）：
  - 灭于 → 大于（GB 55037 4.3.16，"大"被 OCR 成"灭"，并列句无歧义）
  - 单位 ² 修复：'0.35m/人'→'0.35m²/人'、'0.50mr/人'→'0.50m²/人'
    （仅 /人|人次|床|生 人均面积语境，线性米/人在规范里不成立）

用法：
    python -m scripts.fix_chunks_ocr --dry-run     # 预演（默认，逐条 before→after）
    python -m scripts.fix_chunks_ocr --apply       # 实际写入

写入后必须重 ingest（用 reindex_from_chunks，不能用 ingest.py — 后者会从 PDF
重新分块覆盖修复）：
    python -m scripts.reindex_from_chunks --rebuild   # 读修复后 chunks 重建向量

每次跑会在 chunk metadata 加 ocr_fixed_v1=True 标记，便于 audit。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
CHUNKS_DIR = _BACKEND / "data" / "chunks"

# W5 D5 / W7 D3 沉淀的修复字典（每条都人工 review 过上下文，100% 无歧义）
FIX_MAP = {
    # W5 D5 v1 (W6 D1 已修)
    "坏境": "环境",
    "贼市": "城市",
    "改著": "改善",
    "政计": "设计",
    # W7 D3 v2 新增（启示 64 落地）— 启发式 hi 字典 + 已 W6/W7 实战 review
    "店任": "居住",
    "保沪": "保护",
    "宜案用": "宜采用",
    "游患": "游憩",
    "完著": "完善",
    "路同密度": "路网密度",
    "不应低丁": "不应低于",
    "8.0m7人": "8.0m²/人",
    # W7 D4 v3 新增（启示 64 继续）— "大"被 OCR 成"灭"，并列句"不应大于…不应灭于…"无歧义
    "灭于": "大于",
}

# W7 D4：人均面积单位的上标 ² 被 OCR 丢失或误识为 r 的修复。
#   - ² 完全丢失：'0.35m/人' → '0.35m²/人'
#   - ² 误识为 r：'0.50mr/人' → '0.50m²/人'
# 模式 1（数值）：「数字 + m[(r)] + /人|人次|床|生」——人均/每床/每生**面积**指标，
# 线性米/人在规划规范里不成立；已正确的 'm²/人' 与 cosmetic 的 'm2/人' 不会被命中
# （模式要求 m 后直接接 / 或 r/，'m²/'、'm2/' 中间的 ²、2 会让匹配失败）。
UNIT_FIX_PATTERN = re.compile(r"(\d(?:[\d.]*\d)?\s*)m(?:r)?(\s*/\s*(?:人次|人|床|生))")
# 模式 2（表头）：括号内的单位标签 '(m/人)'、'（mr/人)' → '(m²/人)'，与数值保持一致。
# 仅匹配开括号后紧跟的 m，零风险（不会命中 km/cm 或正文中的 m/人 片段）。
UNIT_HEADER_PATTERN = re.compile(r"([（(《\[【])m(?:r)?(\s*/\s*(?:人次|人|床|生))")


def fix_units(text: str) -> tuple[str, int]:
    """修复人均面积单位里丢失/误识的上标 ²（数值 + 表头两类），返回 (new_text, n_subs)。"""
    text, n1 = UNIT_FIX_PATTERN.subn(r"\g<1>m²\g<2>", text)
    text, n2 = UNIT_HEADER_PATTERN.subn(r"\g<1>m²\g<2>", text)
    return text, n1 + n2


# 匹配「数字 m[²r2]? /人床生」单位区域，用于 dry-run 逐条 before→after 核验
# （能同时命中修复前 'm/人' 与修复后 'm²/人'）。
_UNIT_CTX = re.compile(r".{0,15}m[²r2]?\s*/\s*(?:人次|人|床|生).{0,15}")


def _unit_snippet(text: str) -> str:
    """抽取单位修复区域的上下文片段，换行替换成 ⏎ 便于单行展示。"""
    m = _UNIT_CTX.search(text)
    return m.group(0).replace("\n", "⏎") if m else text[:45]


def fix_text(text: str) -> tuple[str, int, int]:
    """对单个 chunk 应用字典替换 + 单位 ² 修复。

    返回 (new_text, n_char_fixes, n_unit_fixes)，两类分开计数便于 audit。
    """
    new_text = text
    n_char = 0
    for err, fix in FIX_MAP.items():
        if err in new_text:
            n_char += new_text.count(err)
            new_text = new_text.replace(err, fix)
    new_text, n_unit = fix_units(new_text)
    return new_text, n_char, n_unit


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                        help="实际写入 chunks 文件（默认仅 dry-run）")
    parser.add_argument("--chunks-dir", type=Path, default=CHUNKS_DIR)
    args = parser.parse_args()

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"\n🔧 OCR 修复模式：{mode}\n")
    print(f"   修复字典: {FIX_MAP}")
    print(f"   chunks 目录: {args.chunks_dir}\n")

    total_files = 0
    total_chunks_changed = 0
    total_char_fixes = 0
    total_unit_fixes = 0
    file_summary = []
    unit_audit = []  # (spec_code, clause, before_snippet, after_snippet)

    for jf in sorted(args.chunks_dir.glob("*.json")):
        if jf.name.startswith("_"):
            continue
        data = json.loads(jf.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            continue

        file_changed = 0
        file_repl = 0
        for ck in data:
            if not isinstance(ck, dict):
                continue
            text = ck.get("text", "")
            if not text:
                continue
            new_text, n_char, n_unit = fix_text(text)
            n_repl = n_char + n_unit
            if n_repl > 0:
                file_changed += 1
                file_repl += n_repl
                total_char_fixes += n_char
                total_unit_fixes += n_unit
                if n_unit > 0:
                    unit_audit.append((
                        ck.get("spec_code", "?"), ck.get("clause", "?"),
                        _unit_snippet(text), _unit_snippet(new_text),
                    ))
                if args.apply:
                    ck["text"] = new_text
                    ck["ocr_fixed_v1"] = True

        if file_changed:
            total_files += 1
            total_chunks_changed += file_changed
            file_summary.append((jf.name, file_changed, file_repl))
            if args.apply:
                jf.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

    print(f"📊 影响文件：{total_files} 个")
    print(f"📊 影响 chunks：{total_chunks_changed} 条")
    print(f"📊 字典替换：{total_char_fixes} 处 ｜ 单位 ² 修复：{total_unit_fixes} 处\n")

    print(f"{'文件':<32} | chunks | 替换数")
    print("-" * 60)
    for name, n_ck, n_repl in file_summary:
        print(f"{name:<32} | {n_ck:>6} | {n_repl:>6}")

    if unit_audit:
        print(f"\n🔬 单位 ² 修复逐条核验（{len(unit_audit)} 条 chunk）：")
        print("-" * 60)
        for sc, cl, before, after in unit_audit:
            print(f"  [{sc} {cl}]")
            print(f"    - {before}")
            print(f"    + {after}")

    if not args.apply:
        print(f"\n💡 dry-run 完成。如确认无误，加 --apply 实际写入。")
        print(f"   后续：python -m scripts.ingest_chunks_to_qdrant  # 重建向量")
    else:
        print(f"\n✅ 已写入 chunks 文件 + 加 ocr_fixed_v1=True 标记")
        print(f"   ⚠️  必须重 ingest 才能让 RAG 检索到修复后的内容：")
        print(f"      python -m scripts.reindex_from_chunks --rebuild")


if __name__ == "__main__":
    main()

"""批量修 chunks 里的 OCR 系统性错字（启示 49/64 落地修复）。

三类修复：
  1. FIX_MAP 精确错字替换（W5 D5 → W7 D4 累积，每条人工 review 上下文无歧义）
  2. fix_units 正则修复人均面积单位里被 OCR 丢失/误识的上标 ²（W7 D4 新增）
  3. strip_page_furniture 剥「住房城乡建设部信息公开 / 浏览专用」页脚水印 + 相邻页码
     （W7 OCR 修复线新增，见下）

W7 OCR 修复线新增（第 3 类 · 覆盖面最大的一类）：
  这批 PDF 带住建部页脚水印，被 OCR 当正文抓进 chunk —— **1209/10785 条（11.2%）受污染**。
  且其中 776 条水印落在**正文中间**，把一句规范切成两半，例如
  GB 55037-2022 11.0.6：「…均应符合消 / 住房城乡建 / 防安全要求」
  ——LLM 读到断句可能引错原文（红线 3 风险），不只是"噪声"问题。

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
    # W7 D10 v4 新增（启示 71）— 新规范"占用次数法"发现的系统性 OCR 错字。
    # 每条都逐一查过全部上下文，确认是非词错字且无合法边界命中（红线）。
    # 已排除危险候选：属住(属性/居住 歧义)、素引(因素引起 边界)。
    "室间": "空间", "轴助": "辅助", "堆护": "维护", "观定": "规定",
    "其备": "具备", "工其": "工具", "人库": "入库", "其体": "具体",
    "安金": "安全", "城币": "城市", "了列": "下列", "数括": "数据",
    "系疏": "系统",
    # V2 期 · 全语料 OCR 体检 v5（启示 74）— LLM 校对出 8 候选，过 context-verify 仅 2 条幸存。
    # 已毙 6 条（红线保护）：录→绿 / 说→设 / 高→尚（高频常用单字，会毁"记录/说明/高度"）；
    #   区城→区域（命中"地区|城市""山区|城市道路"等 7 处合法边界）；混地→湿地（命中"多混地震"）；
    #   城面→城市（仅出现在不可救的 mode-c 乱码块里，低价值）。
    "指施": "措施",   # 55 处均为"措施"语境；"指施工/指施设"全语料 = 0，无合法边界
    "规刘": "规划",   # 43 处均为"规划"；刘=姓氏，"规刘"无合法成词
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


def _rejoin_snippet(before: str, after: str) -> tuple[str, str] | None:
    """若水印夹在正文中间（删掉后句子复原），返回 (before_ctx, after_ctx)；否则 None。

    判定：原文里存在「非水印正文行 → 一段被删行 → 非水印正文行」的夹心结构。
    只是为 dry-run 出人可读的核验样例，不参与修复逻辑。
    """
    lines = before.split("\n")
    for i, ln in enumerate(lines):
        if ln.strip() not in WATERMARK_LINES:
            continue
        # 往前找最近的保留行、往后找最近的保留行
        prev = next(
            (lines[j] for j in range(i - 1, -1, -1)
             if lines[j].strip() and lines[j].strip() not in WATERMARK_LINES
             and not _PAGE_NUM_RE.match(lines[j].strip())),
            None,
        )
        nxt = next(
            (lines[j] for j in range(i + 1, len(lines))
             if lines[j].strip() and lines[j].strip() not in WATERMARK_LINES
             and not _PAGE_NUM_RE.match(lines[j].strip())),
            None,
        )
        if prev and nxt:
            return (
                f"…{prev.strip()[-18:]} ⏎[水印块]⏎ {nxt.strip()[:18]}…",
                f"…{prev.strip()[-18:]} ⏎ {nxt.strip()[:18]}…",
            )
    return None


def _unit_snippet(text: str) -> str:
    """抽取单位修复区域的上下文片段，换行替换成 ⏎ 便于单行展示。"""
    m = _UNIT_CTX.search(text)
    return m.group(0).replace("\n", "⏎") if m else text[:45]


# ── 第 3 类：页脚水印 + 相邻页码 ──────────────────────────────────────
#
# 为什么用**精确白名单**而不是正则泛化：
#   全语料扫出 24 种含「住房城乡建/信息公开/浏览专用」的整行形态，其中 23 种是水印
#   被 OCR 截断的残片，但**第 24 种是正经条文正文**：
#     "馆一般在20 万人口以上的城市设置。2017 年国家发展改革委住房城乡建设部印发《关于规"
#   写成 `住房城乡建设部.*` 之类的正则就会删掉真条文（红线 1/2）。
#   所以只删「整行 strip 后完全等于」下列已核形态之一的行——宁可漏删新变体，
#   也不误删条文；新变体会在 dry-run 的"未收录形态"里报出来。
WATERMARK_LINES: frozenset[str] = frozenset({
    # 完整形态
    "住房城乡建设部信息公开", "浏览专用",
    # OCR 把水印截断/糊字的残片（逐条查过上下文，均为页脚，无正文语义）
    "住房城乡建设部信息公", "住房城乡建设部", "信息公开", "住房城乡建",
    "住房城乡建浏览专用", "住房城乡建设浏览专用", "住房城乡建设部信",
    "住房城乡建设部信息", "住房城乡建设", "住房城乡建设部信息公升",
    "部信息公开", "设部信息公开", "住房城乡建设部信隐", "住房城乡建设部停",
    "住房城乡建谈浏览专用", "住房城乡建设部信愿", "郄信息公开", "住房城乡建德",
    "住房城乡建设部倍", "住房城乡建设部信A", "住房城乡建馈部信息公开",
})

# 页码：紧贴水印行的纯数字行。只在**与被删水印行相邻**时才删——
# 否则会误删条文里的列项序号（"1"、"2"）。
_PAGE_NUM_RE = re.compile(r"^\d{1,4}$")


def strip_page_furniture(text: str) -> tuple[str, int, int]:
    """删掉页脚水印行 + 紧贴它的页码行。

    Returns:
        (new_text, n_watermark_lines, n_page_num_lines)

    注意只做**整行删除**，不改任何保留行的字符——所以不可能改动规范用词（红线 3）。
    删除后相邻行自然接上，被水印切断的句子随之复原。
    """
    lines = text.split("\n")
    is_wm = [ln.strip() in WATERMARK_LINES for ln in lines]
    # 页码行：自身是纯数字，且左右任一侧是水印行
    is_pg = [
        bool(_PAGE_NUM_RE.match(ln.strip()))
        and ((i > 0 and is_wm[i - 1]) or (i + 1 < len(lines) and is_wm[i + 1]))
        for i, ln in enumerate(lines)
    ]
    kept = [ln for i, ln in enumerate(lines) if not is_wm[i] and not is_pg[i]]
    return "\n".join(kept), sum(is_wm), sum(is_pg)


def fix_text(text: str) -> tuple[str, int, int, int]:
    """对单个 chunk 应用字典替换 + 单位 ² 修复 + 页脚水印剥离。

    返回 (new_text, n_char_fixes, n_unit_fixes, n_furniture_lines)，分类计数便于 audit。
    """
    new_text = text
    n_char = 0
    for err, fix in FIX_MAP.items():
        if err in new_text:
            n_char += new_text.count(err)
            new_text = new_text.replace(err, fix)
    new_text, n_unit = fix_units(new_text)
    new_text, n_wm, n_pg = strip_page_furniture(new_text)
    return new_text, n_char, n_unit, n_wm + n_pg


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
    total_furniture = 0
    total_rejoined = 0  # 水印夹在正文中间、删掉后句子复原的次数
    file_summary = []
    unit_audit = []  # (spec_code, clause, before_snippet, after_snippet)
    rejoin_audit = []  # (spec_code, clause, before_ctx, after_ctx)
    # dry-run 报"含水印关键词但未收录到白名单"的整行形态 → 提示是否要补白名单
    unknown_wm: dict[str, int] = {}

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
            # 记录含水印关键词但未收录白名单的整行（可能是新变体，也可能是正经条文）
            for ln in text.split("\n"):
                s = ln.strip()
                if s and s not in WATERMARK_LINES and any(
                    kw in s for kw in ("住房城乡建", "信息公开", "浏览专用")
                ):
                    unknown_wm[s] = unknown_wm.get(s, 0) + 1

            new_text, n_char, n_unit, n_furn = fix_text(text)
            n_repl = n_char + n_unit + n_furn
            if n_repl > 0:
                file_changed += 1
                file_repl += n_repl
                total_char_fixes += n_char
                total_unit_fixes += n_unit
                total_furniture += n_furn
                if n_unit > 0:
                    unit_audit.append((
                        ck.get("spec_code", "?"), ck.get("clause", "?"),
                        _unit_snippet(text), _unit_snippet(new_text),
                    ))
                # 断句复原：水印块前后都还有正文 → 删掉后句子接上（这才是质量收益）
                if n_furn > 0:
                    ctx = _rejoin_snippet(text, new_text)
                    if ctx is not None:
                        total_rejoined += 1
                        if len(rejoin_audit) < 12:
                            rejoin_audit.append(
                                (ck.get("spec_code", "?"), ck.get("clause", "?"), *ctx)
                            )
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
    print(f"📊 字典替换：{total_char_fixes} 处 ｜ 单位 ² 修复：{total_unit_fixes} 处")
    print(f"📊 页脚水印/页码行删除：{total_furniture} 行 "
          f"｜ 其中断句复原 {total_rejoined} 条 chunk\n")

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

    if rejoin_audit:
        print(f"\n🔬 断句复原样例（共 {total_rejoined} 条，抽 {len(rejoin_audit)} 条核验）：")
        print("-" * 60)
        for sc, cl, before, after in rejoin_audit:
            print(f"  [{sc} {cl}]")
            print(f"    - {before}")
            print(f"    + {after}")

    if unknown_wm:
        print(f"\n⚠️  含水印关键词但**未收录白名单**的整行（{len(unknown_wm)} 种）——")
        print("    逐条判断：是水印新变体就补进 WATERMARK_LINES，是正经条文就放着别动。")
        print("-" * 60)
        for s, n in sorted(unknown_wm.items(), key=lambda kv: -kv[1]):
            print(f"  {n:4d}× {s!r}")

    if not args.apply:
        print(f"\n💡 dry-run 完成。如确认无误，加 --apply 实际写入。")
        print(f"   后续：python -m scripts.ingest_chunks_to_qdrant  # 重建向量")
    else:
        print(f"\n✅ 已写入 chunks 文件 + 加 ocr_fixed_v1=True 标记")
        print(f"   ⚠️  必须重 ingest 才能让 RAG 检索到修复后的内容：")
        print(f"      python -m scripts.reindex_from_chunks --rebuild")


if __name__ == "__main__":
    main()

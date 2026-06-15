"""PDF 分块器：按"条"切分，遵守 docs/design/chunker_design_v0.1.md。

输入：单个 PDF 路径 + domain
输出：list[Chunk]

硬约束（CLAUDE.md E.1，铁律）：
  - 以「条款」为基本单元
  - 单 chunk 字符数 ∈ [MIN_CHUNK_SIZE, MAX_CHUNK_SIZE]
  - 表格 / 公式独立成块
  - 元数据（规范号 / 章节 / 条文号 / 页码）不可丢失

实现策略（详见设计文档 §3 算法流程）：
  Phase A: pymupdf 按页提取 text + 字体信息（含 bold）
  Phase B: 状态机识别 章 / 节 / 条 / 表 / 公式 / 附录
  Phase C: 切块（超长按子项切、过短同节合并）
  Phase D: 元数据注入
  Phase E: 输出 list[Chunk]
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

import fitz  # pymupdf

logger = logging.getLogger(__name__)

# ── 硬约束（CLAUDE.md E.1）────────────────────────────────
MAX_CHUNK_SIZE = 800
MIN_CHUNK_SIZE = 50

# ── 结构识别正则 ────────────────────────────────────────
# 章：行首数字 + 空格 + 非数字标题（不含小数点）
RE_CHAPTER = re.compile(r"^\s*(\d{1,2})\s+\S")
# 节：行首 X.Y + 空格
RE_SECTION = re.compile(r"^\s*(\d{1,2}\.\d{1,2})\s+\S")
# 条：行首 X.Y.Z 或 X.Y.Z.W；后续可能是空白、中文，或行尾
# OCR 经常吃掉条文号后空格，所以用 negative lookahead 而非要求 \s
RE_CLAUSE_3 = re.compile(r"^\s*(\d{1,2}\.\d{1,2}\.\d{1,3})(?!\d)")
RE_CLAUSE_4 = re.compile(r"^\s*(\d{1,2}\.\d{1,2}\.\d{1,3}\.\d{1,3})(?!\d)")
# 「第X条」中文条款（建设标准/条例类，无小数条款号）— 仅 article 回退模式用
# X = 中文数字或阿拉伯数字；排除「第X条例」（避免匹配标题里的"条例"二字）
_CN_NUM = "一二三四五六七八九十百千零〇0-9"
RE_CLAUSE_ARTICLE = re.compile(rf"^\s*第\s*([{_CN_NUM}]{{1,6}})\s*条(?!例)")
RE_CHAPTER_CN = re.compile(rf"^\s*第\s*([{_CN_NUM}]{{1,3}})\s*章")
# 附录内条文：行首 A.0.1 / B.0.1 / C.1.2 等（字母+数字层级）
RE_CLAUSE_APPENDIX = re.compile(r"^\s*([A-Z]\.\d{1,2}(?:\.\d{1,3}){1,2})(?!\d)")
# 表 / 公式 / 附录
RE_TABLE_HEAD = re.compile(r"^\s*表\s*(\d+(?:\.\d+)+)")
RE_FORMULA = re.compile(r"^\s*式\s*[\(（]?\s*(\d+(?:\.\d+)+)")
RE_APPENDIX_START = re.compile(r"^\s*附\s*录\s*[A-ZＡ-Ｚ\d一二三四五六七八九十]")
# 强制性条文关键词（决策 3：bold 主判 + 关键词补充）
# 扫描整段文本前 80 字符（OCR 后 bold 丢失，主要靠关键词）
RE_MANDATORY_KW = re.compile(r"(应|不应|严禁|必须|应符合|应满足|不得)")

# ── 字号阈值（章节识别）─────────────────────────────────
# 国家标准 PDF 章节标题字号通常 ≥ 15pt，正文 ≤ 12pt
SIZE_CHAPTER_MIN = 14.0
SIZE_SECTION_MIN = 12.5
SIZE_APPENDIX_MIN = 14.0  # 真正的附录章节标题，与目录页"附录 X"区分

# ── 文件名解析（决策 1）────────────────────────────────
# 形如：GB 50180-2018《城市居住区规划设计标准》_可搜索.pdf
#       JGJ 39-2016《...》(2019年版)_可搜索.pdf
#       建标 109—2008《...》.pdf
#       GB:T50034-2024《...》_可搜索.pdf  ← / 在文件名里用 : 替代
RE_FILENAME = re.compile(r"^(?P<code>[^《]+?)\s*《(?P<name>[^》]+)》")


def parse_filename(pdf_filename: str) -> tuple[str, str]:
    """从文件名提取标准号与规范全称。失败抛 ValueError。

    规范化规则：
      - "GB:T50034-2024" → "GB/T 50034-2024"
      - "GBT+21741-2021" → "GB/T 21741-2021"
      - "JGJ:T245-2024"  → "JGJ/T 245-2024"
      - "建标 109—2008"  → "建标 109-2008"（— 转 -）
    """
    m = RE_FILENAME.match(pdf_filename.strip())
    if not m:
        raise ValueError(f"无法解析文件名: {pdf_filename}")

    code = m.group("code").strip()
    name = m.group("name").strip()

    # 半角化与符号修正
    code = code.replace("：", ":").replace("　", " ").replace("—", "-").replace("–", "-")

    # 把 ":T" 与 "T+" 这种文件名兼容写法还原为 "/T"
    code = re.sub(r":T(?=\d)", "/T ", code)  # GB:T50034 → GB/T 50034
    code = re.sub(r"T\+(?=\d)", "T ", code)  # GBT+21741 → GBT 21741
    code = re.sub(r"^GBT\s+", "GB/T ", code)  # GBT 21741 → GB/T 21741

    # 在字母与数字间补空格：GB50180 → GB 50180
    code = re.sub(r"([A-Z一-鿿])(?=\d)", r"\1 ", code)

    # 多空格压缩
    code = re.sub(r"\s+", " ", code).strip()

    return code, name


# ── 数据结构 ────────────────────────────────────────────
@dataclass
class Chunk:
    """单个 chunk 的完整数据。任何字段缺失都是 P0 bug。"""

    chunk_id: str  # 主键："GB 50180-2018#5.0.3"
    spec_code: str
    spec_name: str
    chapter: str | None
    section: str | None
    clause: str
    type: Literal["clause", "table", "formula", "appendix"]
    text: str
    page_start: int
    page_end: int
    is_mandatory: bool
    domain: str
    source_pdf: str
    char_count: int

    def to_dict(self) -> dict:
        return asdict(self)


# ── 辅助：字体特征 ──────────────────────────────────────
def _is_bold_span(span: dict) -> bool:
    """pymupdf span 是否粗体：flags 第 4 位 或 字体名含 Bold/黑体/Heavy。"""
    flags = span.get("flags", 0)
    if flags & 16:  # bit 4 = bold
        return True
    font = span.get("font", "")
    return any(kw in font for kw in ("Bold", "bold", "黑体", "Heavy", "Black"))


def _line_is_bold(spans: list[dict]) -> bool:
    return any(_is_bold_span(s) for s in spans)


def _avg_size(spans: list[dict]) -> float:
    sizes = [s.get("size", 0.0) for s in spans]
    return sum(sizes) / len(sizes) if sizes else 0.0


def _has_mandatory_keyword(text: str) -> bool:
    """检测整段文本前 80 字符内是否含强制性关键词。

    OCR 后字体 bold 信息常丢失，关键词成为唯一可靠信号。
    限制在前 80 字以避免长条文里偶然出现的"应"误判。
    """
    head = text[:80]
    # 优先看强制性关键词（应/不应/严禁/必须/不得），排除"宜/不宜/可"
    return bool(re.search(r"(应|不应|严禁|必须|不得)", head))


# ── 主分块函数 ──────────────────────────────────────────
def chunk_pdf(
    pdf_path: str | Path,
    *,
    domain: str,
    source_pdf: str | None = None,
    spec_code_override: str | None = None,
    spec_name_override: str | None = None,
) -> list[Chunk]:
    """对单个 PDF 分块。

    Args:
        pdf_path: PDF 文件绝对路径
        domain: 规范分类（规划 / 建筑 / 景观 / 消防）
        source_pdf: 写入 chunk metadata 的相对路径标识；默认用 pdf 文件名
        spec_code_override: 显式提供 spec_code，跳过文件名解析（用于不规则命名）
        spec_name_override: 显式提供 spec_name

    Returns:
        list[Chunk]，已应用 min/max size 规则
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(pdf_path)

    if spec_code_override and spec_name_override:
        spec_code = spec_code_override
        spec_name = spec_name_override
    else:
        spec_code, spec_name = parse_filename(pdf_path.name)
    source = source_pdf or pdf_path.name
    logger.info(f"[chunker] 处理 {pdf_path.name} → {spec_code} 《{spec_name}》")

    doc = fitz.open(pdf_path)

    def run_pass(article_mode: bool) -> list[Chunk]:
        """单遍切块。article_mode=True 时按「第X条」切（建标/条例类）；
        =False 时按 GB/JGJ 小数条款切（默认，逻辑与原版完全一致）。"""
        chunks: list[Chunk] = []
        state: dict = {
            "chapter": None,
            "section": None,
            "clause": None,
            "buf": [],  # list[str]
            "page_start": None,
            "is_mandatory": False,
            "type": "clause",
            "in_appendix": False,
        }

        def flush() -> None:
            """提交当前累积的 buf 为一个或多个 chunk。"""
            if not state["clause"] or not state["buf"]:
                return
            text = "\n".join(state["buf"]).strip()
            if len(text) < 3:
                state["buf"] = []
                return

            # OCR 后 bold 信息常丢失，flush 时基于整段文本做关键词复检
            if not state["is_mandatory"] and state["type"] in ("clause", "appendix"):
                if _has_mandatory_keyword(text):
                    state["is_mandatory"] = True

            if len(text) > MAX_CHUNK_SIZE and state["type"] in ("clause", "appendix"):
                # 决策 4：超长条文按子项切，clause 加 -N 后缀
                for i, sub in enumerate(_split_long_text(text, MAX_CHUNK_SIZE), start=1):
                    _emit(chunks, sub, state, spec_code, spec_name, domain, source, suffix=f"-{i}")
            else:
                _emit(chunks, text, state, spec_code, spec_name, domain, source)

            state["buf"] = []
            state["is_mandatory"] = False
            state["type"] = "appendix" if state["in_appendix"] else "clause"

        for page_num, page in enumerate(doc, start=1):
            try:
                page_dict = page.get_text("dict")
            except Exception as e:
                logger.warning(f"[chunker] page {page_num} 解析失败：{e}")
                continue

            for block in page_dict.get("blocks", []):
                if block.get("type") != 0:  # 0 = text
                    continue
                for line in block.get("lines", []):
                    spans = line.get("spans", [])
                    if not spans:
                        continue
                    text = "".join(s["text"] for s in spans).strip()
                    if not text:
                        continue
                    line_bold = _line_is_bold(spans)
                    size = _avg_size(spans)

                    # ── 附录开始 ──（仅小数模式；字号 ≥ 章节级 + 短行，避免目录污染）
                    if (
                        not article_mode
                        and not state["in_appendix"]
                        and RE_APPENDIX_START.match(text)
                        and size >= SIZE_APPENDIX_MIN
                        and len(text) <= 30
                    ):
                        flush()
                        state["in_appendix"] = True
                        state["chapter"] = text
                        state["section"] = None
                        state["clause"] = None
                        state["type"] = "appendix"
                        continue

                    # ── 表格头 ──（两模式通用）
                    if m := RE_TABLE_HEAD.match(text):
                        flush()
                        state["clause"] = f"表{m.group(1)}"
                        state["type"] = "table"
                        state["page_start"] = page_num
                        state["is_mandatory"] = False
                        state["buf"].append(text)
                        continue

                    # ── 公式 ──（两模式通用）
                    if m := RE_FORMULA.match(text):
                        flush()
                        state["clause"] = f"式{m.group(1)}"
                        state["type"] = "formula"
                        state["page_start"] = page_num
                        state["is_mandatory"] = False
                        state["buf"].append(text)
                        continue

                    if article_mode:
                        # ── 第X章（章标题，仅元数据）──
                        if RE_CHAPTER_CN.match(text) and len(text) <= 30:
                            flush()
                            state["chapter"] = text
                            state["section"] = None
                            state["clause"] = None
                            continue
                        # ── 第X条（条款边界）──
                        if m := RE_CLAUSE_ARTICLE.match(text):
                            flush()
                            state["clause"] = f"第{m.group(1)}条"
                            state["type"] = "clause"
                            state["page_start"] = page_num
                            state["is_mandatory"] = line_bold or _has_mandatory_keyword(text)
                            state["buf"].append(text)
                            continue
                    else:
                        # ── 条（先匹配 4 级，再 3 级，再附录 A.0.1）──
                        if m := (
                            RE_CLAUSE_4.match(text)
                            or RE_CLAUSE_3.match(text)
                            or (RE_CLAUSE_APPENDIX.match(text) if state["in_appendix"] else None)
                        ):
                            flush()
                            state["clause"] = m.group(1)
                            state["type"] = "appendix" if state["in_appendix"] else "clause"
                            state["page_start"] = page_num
                            state["is_mandatory"] = line_bold or _has_mandatory_keyword(text)
                            state["buf"].append(text)
                            continue

                        # ── 节（X.Y）──
                        if RE_SECTION.match(text) and not RE_CLAUSE_3.match(text):
                            # 节标题字号显著大于正文，且为短行
                            if (size >= SIZE_SECTION_MIN and len(text) <= 30) or line_bold:
                                flush()
                                state["section"] = text
                                state["clause"] = None
                                continue

                        # ── 章（X）──
                        if (
                            RE_CHAPTER.match(text)
                            and not RE_SECTION.match(text)
                            and not RE_CLAUSE_3.match(text)
                        ):
                            # 章标题：字号显著大 + 长度合理 + 含足够中文
                            cn_count = sum(1 for ch in text if "一" <= ch <= "鿿")
                            if (
                                size >= SIZE_CHAPTER_MIN
                                and 4 <= len(text) <= 25
                                and cn_count >= 2  # 至少 2 个中文字
                            ):
                                flush()
                                state["chapter"] = text
                                state["section"] = None
                                state["clause"] = None
                                continue

                    # ── 默认：累加到当前 chunk ──
                    if state["clause"]:
                        state["buf"].append(text)
                        if line_bold and state["type"] == "clause" and not state["is_mandatory"]:
                            state["is_mandatory"] = True

        flush()  # 末尾 flush
        return _merge_too_short(chunks)

    # 主：小数条款模式。产出过少（建标/条例用「第X条」，小数模式 0 块或仅几个
    # OCR 误识的垃圾块）时跑 article 模式，取块数更多者。
    # 零回归：正常 GB/JGJ 规范小数模式 ≥10 块，不跑 article；即便跑，其「第X条」
    # 命中≈0，max 仍选小数结果。
    chunks = run_pass(article_mode=False)
    if len(chunks) < 10:
        article_chunks = run_pass(article_mode=True)
        if len(article_chunks) > len(chunks):
            logger.info(
                f"[chunker] {pdf_path.name} 小数 {len(chunks)} 块 → 「第X条」{len(article_chunks)} 块（取后者）"
            )
            chunks = article_chunks

    doc.close()
    logger.info(f"[chunker] {pdf_path.name} 完成：{len(chunks)} 个 chunks")
    return chunks


# ── 内部工具 ────────────────────────────────────────────
def _emit(
    chunks: list[Chunk],
    text: str,
    state: dict,
    spec_code: str,
    spec_name: str,
    domain: str,
    source_pdf: str,
    *,
    suffix: str = "",
) -> None:
    """构造并 append 一个 chunk。

    chunk_id 唯一性保证：若 {spec_code}#{clause} 已在 chunks 内出现，
    自动追加 _dN 后缀（OCR 错位/章节误识别可能让同 clause 号被切多次）。
    """
    clause = state["clause"] + suffix
    base_id = f"{spec_code}#{clause}"
    chunk_id = base_id
    # 单部 PDF chunks 数 < 1000，线性扫描成本可接受
    existing_ids = {c.chunk_id for c in chunks}
    dup_n = 1
    while chunk_id in existing_ids:
        chunk_id = f"{base_id}_d{dup_n}"
        dup_n += 1
    page_start = state["page_start"] or 1
    chunks.append(
        Chunk(
            chunk_id=chunk_id,
            spec_code=spec_code,
            spec_name=spec_name,
            chapter=state["chapter"],
            section=state["section"],
            clause=clause,
            type=state["type"],
            text=text,
            page_start=page_start,
            page_end=page_start,  # TODO(W1): 支持跨页 chunk 的 page_end 推导
            is_mandatory=state["is_mandatory"],
            domain=domain,
            source_pdf=source_pdf,
            char_count=len(text),
        )
    )


def _split_long_text(text: str, limit: int) -> list[str]:
    """超长文本按段落（换行）切分；尽量每段不超 limit 字。"""
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    if not paragraphs:
        return [text]

    result: list[str] = []
    current: list[str] = []
    current_len = 0
    for p in paragraphs:
        if current and current_len + len(p) > limit:
            result.append("\n".join(current))
            current = [p]
            current_len = len(p)
        else:
            current.append(p)
            current_len += len(p)
    if current:
        result.append("\n".join(current))
    return result or [text]


def _merge_too_short(chunks: list[Chunk]) -> list[Chunk]:
    """合并过短 clause 到下一个同节 clause。表格 / 公式 / 附录不参与合并。"""
    if not chunks:
        return []

    merged: list[Chunk] = []
    pending: Chunk | None = None
    for c in chunks:
        if pending is not None:
            if c.type == "clause" and pending.section == c.section:
                # 合并 pending → c 前面
                combined = Chunk(
                    chunk_id=pending.chunk_id,  # 用前者 id（更老）
                    spec_code=c.spec_code,
                    spec_name=c.spec_name,
                    chapter=c.chapter,
                    section=c.section,
                    clause=f"{pending.clause}+{c.clause}",
                    type="clause",
                    text=f"{pending.text}\n{c.text}",
                    page_start=pending.page_start,
                    page_end=c.page_end,
                    is_mandatory=pending.is_mandatory or c.is_mandatory,
                    domain=c.domain,
                    source_pdf=c.source_pdf,
                    char_count=pending.char_count + c.char_count + 1,
                )
                merged.append(combined)
                pending = None
                continue
            # 无法合并（type 不同 / 跨节）→ pending 单独输出
            merged.append(pending)
            pending = None

        if c.type == "clause" and c.char_count < MIN_CHUNK_SIZE:
            pending = c
        else:
            merged.append(c)

    if pending:
        merged.append(pending)
    return merged

"""PDF 分块：以"条"为基本单元，遵守 CLAUDE.md E.1 铁律。

输入：PDF 文件路径
输出：List[Chunk]，每个 chunk 含 {text, spec_code, clause, page, is_mandatory, ...}

硬规则（不可违反）：
  - max_chunk_size = 800 字
  - min_chunk_size = 50 字
  - 表格独立成块，不可切散
  - 公式独立成块
  - 元数据（规范号/章节/条文号/页码）不可丢失

W1 实现。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# TODO(W1): 用 pymupdf (fitz) 解析 PDF，按"条"切分

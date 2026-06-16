"""规范现行状态服务（"像查法条"——状态会随时间变化）。

定位：为每条引用标注规范的**现行状态**，让用户一眼看出引的是不是现行有效版本。

设计（经确认）：
  - 默认所有入库规范为「现行」——入库的本就是当时的现行版本。
  - 此处仅登记【例外】：已废止 / 局部废止 / 即将实施。

🔴 红线：状态必须来自**权威来源**（住建部 / 国家标准委公告、规范前言的废止声明），
   **绝不臆断**某规范作废。宁可标「现行」（默认）也不编造「已废止」。

维护：每年扫一次国家标准委公告 + 留意新规范前言"替代"声明，补充下方例外表。
"""

from __future__ import annotations

from typing import Literal

# 4 态（与前端徽章 + CSS token 一一对应）
SpecStatus = Literal["现行", "已废止", "局部废止", "即将实施"]

# ── 例外表：只登记非「现行」的规范 ──────────────────────────────────────
# 格式：标准化 spec_code → {"status", "replaced_by"(可空), "note"(可空)}
# 标准化 = 去空格 + 转大写（见 _normalize），登记时 key 可写常规形式，查时会归一。
#
# 📝 填写示例（确认权威来源后取消注释、替换为真实数据）：
#   "GB 50180-93":   {"status": "已废止",   "replaced_by": "GB 50180-2018",
#                     "note": "2018 版施行起废止"},
#   "GB 50016-2006": {"status": "局部废止", "replaced_by": "GB 50016-2014",
#                     "note": "部分条文经 2014 版修订"},
#   "GB 55XXX-2026": {"status": "即将实施", "replaced_by": None,
#                     "note": "2026-10-01 起施行"},
#
# 当前为空 = 全部按「现行」展示（待按权威公告逐步补录）。
SPEC_STATUS_EXCEPTIONS: dict[str, dict[str, str | None]] = {}


def _normalize(spec_code: str) -> str:
    """归一 spec_code 用于匹配：去所有空格 + 大写（GB/T、CJJ/T 等保留斜杠）。"""
    return (spec_code or "").replace(" ", "").replace("　", "").upper()


# 预归一例外表 key，避免每次查询重复归一
_NORM_EXCEPTIONS = {_normalize(k): v for k, v in SPEC_STATUS_EXCEPTIONS.items()}


def get_spec_status(spec_code: str) -> dict[str, str | None]:
    """返回规范的现行状态。

    Args:
        spec_code: 标准号，如 "GB 50180-2018"。

    Returns:
        {"status": SpecStatus, "replaced_by": str|None, "status_note": str|None}
        未登记的规范默认 {"status": "现行", "replaced_by": None, "status_note": None}。
    """
    info = _NORM_EXCEPTIONS.get(_normalize(spec_code))
    if info is None:
        return {"status": "现行", "replaced_by": None, "status_note": None}
    return {
        "status": info.get("status", "现行"),
        "replaced_by": info.get("replaced_by"),
        "status_note": info.get("note"),
    }

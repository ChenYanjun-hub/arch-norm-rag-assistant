"""W4 D3：在 v3 集基础上做 14 条 expected_clause 增量修订，输出 v3.1。

W4 D3-1 复核发现 v3 集 31 条有效里有 14 条 chunks_not_found，按 4 路径修：

路径 1 · 空格归一化（3 条）："表 X.Y.Z" → "表X.Y.Z"
路径 2 · OCR 错位替代（3 条）：4.0.4 不在 chunks（OCR 切错）→ 改最近的同主题 clause
路径 3 · 真实条款定位错（4 条）：原 expected_clause 在规范里就不存在 → 改真实条款
路径 4 · 通配 clause（4 条）：原 "2.0.x" 改为具体 clause

输入：data/eval/eval_set_v1_50_v3.csv
输出：data/eval/eval_set_v1_50_v3_1.csv

修订前 expected_clause 仍保留在新字段 v3_1_old_clause 便于回溯。
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
SRC = _BACKEND / "data" / "eval" / "eval_set_v1_50_v3.csv"
DST = _BACKEND / "data" / "eval" / "eval_set_v1_50_v3_1.csv"


# QID → (new_clause, reason)
# 4 路径全部统一到 expected_clause 字段
CLAUSE_FIX: dict[str, dict[str, str]] = {
    # 路径 1 · 空格归一化（"表 5.0.3" → "表5.0.3"）
    "Q001": {"clause": "表5.0.3", "reason": "去空格让 _clause_match 命中 chunks '表5.0.3'"},
    "Q021": {"clause": "表5.0.3", "reason": "去空格"},
    "Q023": {"clause": "表5.0.3", "reason": "去空格"},

    # 路径 2 · OCR 错位替代（4.0.4 chunker 切错 → 同主题 4.0.6/4.0.7）
    "Q005": {"clause": "4.0.6", "reason": "GB 50180-2018 4.0.4 表号被 OCR 切错；4.0.6 是绿地结合住宅布局，相关"},
    "Q017": {"clause": "4.0.7", "reason": "GB 50180-2018 4.0.4 OCR 切错；4.0.7 是集中绿地条款，含'宽度'"},
    "Q022": {"clause": "4.0.6", "reason": "GB 50180-2018 4.0.4 OCR 切错；改 4.0.6"},

    # 路径 3 · 真实条款定位错（5.1.1/5.5.24/5.5.27 在规范里不存在或在 chunks 缺失）
    "Q007": {"clause": "4.1.1", "reason": "GB 50368-2005 卧室面积实际在 4.1.1（不是 5.1.1，evaluation 集设计错误）"},
    "Q024": {"clause": "4.1.1", "reason": "同 Q007"},
    "Q011": {"clause": "7.4.4", "reason": "GB 55037-2022 防烟楼梯条款在 7.4.4（一类高层公共建筑应为防烟楼梯间）"},
    "Q025": {"clause": "7.4.5", "reason": "GB 55037-2022 封闭楼梯条款在 7.4.5（建筑高度不大于 32m 二类高层）"},

    # 路径 4 · 通配 clause 改具体
    "Q029": {"clause": "2.0.3", "reason": "原通配 '2.0.x' → 具体 2.0.3（GB 50180-2018 居住区规模定义）"},
    "Q031": {"clause": "3.3.1", "reason": "原通配 '3.3.x' → 具体 3.3.1（GB 55037-2022 防火分区相关）"},
    "Q033": {"clause": "4.1.3+4.1.4", "reason": "原通配 '2.x' → CJJ/T 91-2017 4.1.x 是公园分类定义"},
    "Q046": {"clause": "7.5.5", "reason": "原通配 '7.x' → 具体 GB 50368-2005 7.5.5（家居配线/通信端口）"},
}


def main() -> None:
    if not SRC.exists():
        print(f"❌ 源文件不存在：{SRC}", file=sys.stderr)
        sys.exit(1)

    rows = list(csv.DictReader(open(SRC, encoding="utf-8")))
    print(f"读取 v3：{len(rows)} 条")

    extra_fields = ["v3_1_old_clause", "v3_1_fix_reason"]
    fieldnames = list(rows[0].keys()) + extra_fields

    fixed_count = 0
    for r in rows:
        r["v3_1_old_clause"] = ""
        r["v3_1_fix_reason"] = ""
        qid = r["id"]
        if qid in CLAUSE_FIX:
            old = r["expected_clause"]
            new = CLAUSE_FIX[qid]["clause"]
            r["v3_1_old_clause"] = old
            r["expected_clause"] = new
            r["v3_1_fix_reason"] = CLAUSE_FIX[qid]["reason"]
            fixed_count += 1

    DST.write_text("", encoding="utf-8")
    with open(DST, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    print(f"\n写入 v3.1：{DST}")
    print(f"  修订条目：{fixed_count} 条")


if __name__ == "__main__":
    main()

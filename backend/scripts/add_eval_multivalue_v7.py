"""一次性：给 eval_set_v1_171_v6 增加多值 GT 列 `also_accept`，产出 v7。

背景（2026-W7 评测口径升级）：
    v6 基线中，"同主题多值"题被单值 GT 判死——一个问题多部规范都合法，
    但评测只认一个标准答案。典型：幼儿园/小学服务半径，GB50180 是配套设施标准，
    而 JGJ39（托幼建筑设计）/ GB50442（中小学校设计）才直接写"服务半径"。

    本脚本给这类题加"可接受的备选出处"（also_accept），任一命中即算命中。
    只处理审计确认、且备选原文经核验确实答对题的行；每条留证据。

原则：
    - 不覆盖原集：产出 eval_set_v1_171_v7.csv（在 v6 基础上加 also_accept 列）
    - 只加备选、不改主 GT / query
    - 备选必须原文核验"确实是正确答案"，不能拿"检索返回了它"当理由
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
EVAL_DIR = _BACKEND / "data" / "eval"
SRC = EVAL_DIR / "eval_set_v1_171_v6.csv"
DST = EVAL_DIR / "eval_set_v1_171_v7.csv"
CHANGELOG = _BACKEND.parent / "docs" / "eval" / "2026-W7_multivalue_v7_changelog.md"

# also_accept 列格式：`spec|clause;spec|clause`
# id -> (also_accept 值, 备选原文摘要, 判定理由)
JGJ39 = "JGJ 39-2016|3.1.3"  # "托儿所、幼儿园的服务半径宜为300m~500m"
GB50442 = "GB 50442 - 20XX|4.2.1"  # "中小学服务半径…小学步行10分钟以内"

MULTIVALUE: dict[str, tuple[str, str, str]] = {
    "Q001": (JGJ39, "JGJ39 3.1.3=托幼服务半径宜300~500m",
             "问'幼儿园服务半径'，JGJ39(托幼建筑设计)直接写服务半径，与主 GT GB50180 均合法。"),
    "Q021": (JGJ39, "JGJ39 3.1.3=托幼服务半径宜300~500m",
             "问'幼儿园280m/8班是否合规'，服务半径依据在 JGJ39 3.1.3。"),
    "Q026": (JGJ39, "JGJ39 3.1.3=托幼服务半径宜300~500m",
             "问'幼儿园350m服务半径是否合规'，JGJ39 3.1.3 是直接依据。"),
    "Q034": (JGJ39, "JGJ39 3.1.3=托幼服务半径宜300~500m",
             "问'幼儿园服务半径上限'，JGJ39 3.1.3 直接给上限。"),
    "Q099": (JGJ39, "JGJ39 3.1.3=托幼服务半径宜300~500m",
             "复合题含'幼儿园服务半径'，JGJ39 3.1.3 覆盖该半，与主 GT 并行合法。"),
    "Q023": (GB50442, "GB50442 4.2.1=中小学服务半径(小学步行10分钟)",
             "问'小学600m服务半径是否合规'，GB50442(中小学校设计)直接给依据。"),
}


def main() -> None:
    if not SRC.exists():
        print(f"❌ 源集不存在: {SRC}", file=sys.stderr)
        sys.exit(1)
    with SRC.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        cols = list(reader.fieldnames or [])
        rows = list(reader)

    if "also_accept" not in cols:
        cols.append("also_accept")

    applied = []
    for r in rows:
        r.setdefault("also_accept", "")
        rid = r.get("id", "")
        if rid in MULTIVALUE:
            val, alt_txt, reason = MULTIVALUE[rid]
            r["also_accept"] = val
            applied.append((rid, r.get("query", "")[:30], val, alt_txt, reason))

    with DST.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)

    lines = [
        "# 评测集多值 GT 变更日志 · v6 → v7",
        "",
        "> 评测口径升级：给「同主题多值」题增加可接受的备选出处（`also_accept` 列），任一命中即算命中。",
        f"> 源集 `eval_set_v1_171_v6.csv` → `eval_set_v1_171_v7.csv`，共标注 **{len(applied)}** 条多值题。",
        "> 备选均经 chunks 原文核验「确实是正确答案」；主 GT 不变。",
        "",
        "| id | 问题 | 备选出处(also_accept) | 备选原文 | 判定理由 |",
        "|---|---|---|---|---|",
    ]
    for rid, q, val, alt_txt, reason in applied:
        lines.append(f"| {rid} | {q} | `{val}` | {alt_txt} | {reason} |")
    CHANGELOG.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"✅ 写出 {DST.name}（{len(rows)} 行，多值标注 {len(applied)} 条）")
    print(f"✅ 变更日志 → {CHANGELOG}")
    for rid, q, val, *_ in applied:
        print(f"   {rid}: +{val}")


if __name__ == "__main__":
    main()

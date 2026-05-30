"""基于实际入库规范，把 eval_set_v1_50.csv 修订为 v2。

修订原则（W2 Day 3 诊断结论）：
1. 评测集 v1 默认采用 2010-2019 老规范号；但规范库主要入库 2021-2024 通用规范
2. 改 expected_spec 为入库的对应规范（强制性通用规范取代旧标准的部分）
3. 完全无替代的，置空 expected_spec → 评测时跳过（标记 v2_status=dropped）
4. expected_clause 暂保留原值（OCR 编号问题 W3 重 ingest 后再修）

输出：data/eval/eval_set_v1_50_v2.csv

字段新增：
    v2_status         : kept / remapped / dropped
    v2_remap_reason   : 说明改的原因
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
SRC = _BACKEND / "data" / "eval" / "eval_set_v1_50.csv"
DST = _BACKEND / "data" / "eval" / "eval_set_v1_50_v2.csv"


# 已知的强制性通用规范取代关系（基于 GB 55xxx 系列政策）
SPEC_REMAP: dict[str, tuple[str, str]] = {
    "GB 50016-2014": ("GB 55037-2022", "GB 50016-2014《建筑设计防火规范》未入库，由 GB 55037-2022《建筑防火通用规范》取代强制性部分"),
    "GB 50352-2019": ("GB 55031-2022", "GB 50352-2019《民用建筑设计统一标准》未入库，由 GB 55031-2022《民用建筑通用规范》取代强制性部分"),
    "GB 50096-2011": ("GB 50368-2005", "GB 50096-2011《住宅设计规范》未入库，本库仅 GB 50368-2005《住宅项目规范》"),
}

# 无替代，本次评测剔除
SPEC_DROP: dict[str, str] = {
    "GB 50099-2011": "GB 50099-2011《中小学校设计规范》未入库且无替代",
    "GB 50137-2011": "GB 50137-2011《城市用地分类标准》未入库且无替代",
    "GB 51192-2016": "GB 51192-2016《公园设计规范》未入库且无替代",
    "GB 50068-2018": "GB 50068-2018《建筑结构可靠性设计统一标准》未入库且无替代",
    "GB 50011-2010": "GB 50011-2010《建筑抗震设计规范》未入库且无替代",
}


def main() -> None:
    if not SRC.exists():
        print(f"❌ 源 CSV 不存在：{SRC}", file=sys.stderr)
        sys.exit(1)

    with open(SRC, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    new_rows: list[dict[str, str]] = []
    n_kept = n_remap = n_drop = n_no_spec = 0

    for r in rows:
        expected = (r.get("expected_spec") or "").strip()
        v2 = dict(r)  # 拷贝

        if not expected:
            # 原本就没 expected（边界兜底类）
            v2["v2_status"] = "no_expected"
            v2["v2_remap_reason"] = ""
            n_no_spec += 1
        elif expected in SPEC_REMAP:
            new_spec, reason = SPEC_REMAP[expected]
            v2["expected_spec"] = new_spec
            v2["v2_status"] = "remapped"
            v2["v2_remap_reason"] = reason
            n_remap += 1
        elif expected in SPEC_DROP:
            v2["expected_spec"] = ""  # 置空 → 评测跳过
            v2["v2_status"] = "dropped"
            v2["v2_remap_reason"] = SPEC_DROP[expected]
            n_drop += 1
        else:
            v2["v2_status"] = "kept"
            v2["v2_remap_reason"] = ""
            n_kept += 1

        new_rows.append(v2)

    fieldnames = list(rows[0].keys()) + ["v2_status", "v2_remap_reason"]
    with open(DST, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(new_rows)

    total = len(rows)
    print(f"✅ v2 已生成：{DST}")
    print(f"\n修订统计（总 {total} 条）：")
    print(f"  kept       : {n_kept:3d}  （原 expected_spec 在库，无需改）")
    print(f"  remapped   : {n_remap:3d}  （expected_spec 替换为通用规范）")
    print(f"  dropped    : {n_drop:3d}  （无入库替代，置空 expected_spec）")
    print(f"  no_expected: {n_no_spec:3d}  （原本无 expected_spec，边界兜底类）")
    print(f"\n下一步：")
    print(f"  cd backend && .venv/bin/python -m scripts.run_eval --csv {DST.relative_to(_BACKEND)}")


if __name__ == "__main__":
    main()

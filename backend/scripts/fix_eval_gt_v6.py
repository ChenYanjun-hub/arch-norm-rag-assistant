"""一次性：修正 eval_set_v1_171_v5 中审计确认的 ground-truth 标注错误，产出 v6。

背景（2026-W7 baseline 审计）：
    v5 基线 strict Hit@5 = 78.8% 被严重低估。逐条读 29 条 strict-miss 的
    「期望条原文 vs 检索 top1 原文」后确认：其中约 10 条是 GT 条文号标错——
    期望条指向的原文根本不对题，检索 top1 才是正解。

    本脚本只修正「原期望条内容明显不对题 + 新条内容明显对题」的案例，
    每条附证据（原条内容 / 新条内容 / 为何改）。多值/复合/GT可疑/OCR 缺陷
    案例不在此处理（见审计文档，单独处置）。

原则：
    - 不覆盖原集：产出 eval_set_v1_171_v6.csv
    - 每条修正留证据 → 同时写 changelog markdown（可审计、面试可复述）
    - 保守：只改 spec/clause 标注，不动 query / answer_summary
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
EVAL_DIR = _BACKEND / "data" / "eval"
SRC = EVAL_DIR / "eval_set_v1_171_v5.csv"
DST = EVAL_DIR / "eval_set_v1_171_v6.csv"
CHANGELOG = _BACKEND.parent / "docs" / "eval" / "2026-W7_gt_fix_v6_changelog.md"

# id -> (new_spec, new_clause, 原期望, 原期望内容摘要, 新条内容摘要, 判定理由)
# 只列「安全修正」：原期望条内容明显不对题，新条内容明显对题（均来自 chunks 原文核对）
FIXES: dict[str, tuple[str, str, str, str, str, str]] = {
    "Q003": ("GB 50180-2018", "2.0.2", "GB 50180-2018 / 2.0.5",
             "2.0.5=居住街坊(1000~3000人)", "2.0.2=十五分钟生活圈居住区(50000~100000人)",
             "问'十五分钟生活圈人口规模'，答案在 2.0.2；原标 2.0.5 是居住街坊，错。"),
    "Q027": ("GB 50180-2018", "2.0.2", "GB 50180-2018 / 2.0.5",
             "2.0.5=居住街坊", "2.0.2=十五分钟生活圈居住区定义",
             "问'什么是十五分钟生活圈'，定义在 2.0.2；原标 2.0.5 错。"),
    "Q031": ("GB 55037-2022", "4.1.2", "GB 55037-2022 / 3.3.1",
             "3.3.1=防火间距(>100m建筑)", "4.1.2=防火分区划分规定",
             "问'什么是防火分区'，答案在 4.1.2；原标 3.3.1 是防火间距，错。"),
    "Q047": ("GB 55037-2022", "4.3.16", "GB 55037-2022 / 5.3.1",
             "5.3.1=耐火等级应为一级", "4.3.16=每个防火分区最大面积≤1500m²",
             "问'防火分区1000m²是否合规'，答案在 4.3.16；原标 5.3.1 是耐火等级，错。"),
    "Q006": ("JGJ 99-2015", "2.1.1", "GB 55031-2022 / 3.1.1",
             "GB55031 3.1.1=建筑面积计算", "JGJ99 2.1.1=高层民用建筑(10层/28m)定义",
             "问'高层建筑指什么'，定义在 JGJ99 2.1.1；原标 GB55031 3.1.1 是建筑面积计算，错。"),
    "Q018": ("GB 50763-2012", "4.4.2", "GB 55037-2022 / 6.3",
             "GB55037 6.3.1=电梯井防火", "GB50763 4.4.2=无障碍坡道净宽≥2.00m",
             "问'无障碍坡道设计要求'，答案在 GB50763(无障碍设计规范) 4.4.2；原标 GB55037 6.3 是电梯井，错。"),
    "Q100": ("CJJ/T 75-2023", "3.0.2", "GB 50180-2018 / 4.0.7",
             "GB50180 4.0.7=居住街坊集中绿地", "CJJ/T75 3.0.2=城市道路绿地率/行道树",
             "问'城市道路两侧绿地'，答案在 CJJ/T75(道路绿化规范) 3.0.2；原标 GB50180 4.0.7 是居住街坊绿地，错。"),
    "Q019": ("GB 50067-2014", "4.3.3", "GB 55037-2022 / 7.1.8",
             "GB55037 7.1.8=室内疏散楼梯间", "GB50067 4.3.3=消防车道净空高度/净宽≥4m",
             "问'消防车道净宽净高'，答案在 GB50067 4.3.3；原标 GB55037 7.1.8 是疏散楼梯间，错。"),
    "Q005": ("GB 50180-2018", "表4.0.2", "GB 50180-2018 / 4.0.6",
             "4.0.6=绿地计算方法", "表4.0.2=居住街坊绿地率(含最小值)",
             "问'绿地率下限'，国标下限在表4.0.2；原标 4.0.6 是计算方法，非阈值。"),
    "Q033": ("CJJ/T 91-2017", "4.1.1", "CJJ/T 91-2017 / 4.1.3+4.1.4",
             "4.1.3/4.1.4=专类公园/社区公园(子类)", "4.1.1=公园绿地(正解, 但 OCR 毁成'public parl R')",
             "问'什么是公园绿地'，定义在 4.1.1；原标 4.1.3 是子类。⚠️同时 4.1.1 chunk OCR 损坏，见 OCR 缺陷清单。"),
}


def main() -> None:
    if not SRC.exists():
        print(f"❌ 源集不存在: {SRC}", file=sys.stderr)
        sys.exit(1)
    with SRC.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        cols = reader.fieldnames or []
        rows = list(reader)

    applied: list[tuple[str, str, str, str, str, str]] = []
    for r in rows:
        rid = r.get("id", "")
        if rid in FIXES:
            new_spec, new_clause, old_disp, *_ev = FIXES[rid]
            r["expected_spec"] = new_spec
            r["expected_clause"] = new_clause
            applied.append((rid, old_disp, f"{new_spec} / {new_clause}", *FIXES[rid][3:6]))

    with DST.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)

    # changelog
    lines = [
        "# 评测集 GT 修正变更日志 · v5 → v6",
        "",
        "> 依据 2026-W7 baseline 审计（逐条核对期望条原文 vs 检索 top1 原文）。",
        f"> 源集 `eval_set_v1_171_v5.csv` → 产出 `eval_set_v1_171_v6.csv`，共修正 **{len(applied)}** 条 GT 标注错误。",
        "> 仅修正「原期望条内容明显不对题 + 新条内容明显对题」的案例；多值/复合/OCR 缺陷不在此处理。",
        "",
        "| id | 原期望(错) | 原期望内容 | 新期望(对) | 新条内容 | 判定理由 |",
        "|---|---|---|---|---|---|",
    ]
    for rid, old_disp, new_disp, old_txt, new_txt, reason in applied:
        lines.append(f"| {rid} | {old_disp} | {old_txt} | {new_disp} | {new_txt} | {reason} |")
    CHANGELOG.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"✅ 写出 {DST.name}（{len(rows)} 行，修正 {len(applied)} 条）")
    print(f"✅ 变更日志 → {CHANGELOG}")
    for rid, old_disp, new_disp, *_ in applied:
        print(f"   {rid}: {old_disp}  →  {new_disp}")


if __name__ == "__main__":
    main()

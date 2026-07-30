"""审计二级分类表对语料的覆盖情况（新增规范后必跑）。

用法：
    cd backend && python -m scripts.audit_taxonomy

输出：
  - 每域二级分组概览（组数 / 各组部数 / 导航扫描面）
  - ⚠️ 语料里有但分类表未登记的规范（必须补）
  - ⚠️ 分类表里有但语料里没有的规范（拼写错 / 规范已下线）
  - ⚠️ 二级分类名不在 SUBCATEGORY_ORDER 里的（不会按顺序展示）

退出码：有未登记项时返回 1，便于以后接 CI。
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.services.spec_taxonomy import (  # noqa: E402
    SUBCATEGORY_BY_SPEC,
    SUBCATEGORY_ORDER,
    SUBCAT_MIN_SPECS,
    get_subcategory,
    group_by_subcategory,
    is_subdivided,
    normalize_spec_code,
)


def load_corpus() -> dict[str, dict[str, str]]:
    """扫 chunks/*.json → {domain: {spec_code: spec_name}}（与 stats.py 同源）。"""
    by_domain: dict[str, dict[str, str]] = defaultdict(dict)
    chunks_dir = Path(settings.chunks_dir)
    for jf in sorted(chunks_dir.glob("*.json")):
        if jf.name.startswith("_"):
            continue
        data = json.loads(jf.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            continue
        for ck in data:
            if isinstance(ck, dict) and ck.get("spec_code"):
                by_domain[ck.get("domain") or "未分类"][ck["spec_code"]] = (
                    ck.get("spec_name") or ""
                )
    return by_domain


def scan_cost_flat(n: int) -> float:
    """平铺时找到目标规范的期望扫描行数。

    模型：目标在 n 行里等概率出现，从上往下扫 → 期望 (n+1)/2。
    这是"导航成本"的可计算代理指标，避免只说"看起来更清楚"这种主观判断。
    """
    return (n + 1) / 2 if n else 0.0


def scan_cost_grouped(sizes: list[int]) -> float:
    """二级分组时的期望扫描行数 = 扫分类行 + 扫组内规范行。

    先在 k 个分类里找到目标所属分类（期望 (k+1)/2 行），
    再在该组 m 行里找到目标（期望 (m+1)/2 行）；对所有目标按组大小加权平均。
    """
    n = sum(sizes)
    if not n:
        return 0.0
    k = len(sizes)
    within = sum(m * (m + 1) / 2 for m in sizes) / n
    return (k + 1) / 2 + within


def main() -> int:
    corpus = load_corpus()
    problems = 0
    cost_rows: list[tuple[str, int, float, float]] = []

    print("=" * 72)
    print("二级分类覆盖审计")
    print("=" * 72)

    all_codes: set[str] = set()
    for domain, specs in sorted(corpus.items(), key=lambda kv: -len(kv[1])):
        all_codes |= set(specs)
        n = len(specs)
        items = [{"spec_code": c, "spec_name": specs[c]} for c in sorted(specs)]
        groups = group_by_subcategory(domain, items)

        if groups is None:
            reason = (
                f"域内 {n} 部 < 阈值 {SUBCAT_MIN_SPECS}"
                if domain not in SUBCATEGORY_ORDER or n < SUBCAT_MIN_SPECS
                else "未定义"
            )
            flat = scan_cost_flat(n)
            cost_rows.append((domain, n, flat, flat))
            print(
                f"\n【{domain}】{n} 部 · 不细分（{reason}）· "
                f"期望扫描 {flat:.1f} 行"
            )
            continue

        sizes = [len(g) for _, g in groups]
        flat, grouped_cost = scan_cost_flat(n), scan_cost_grouped(sizes)
        cost_rows.append((domain, n, flat, grouped_cost))
        print(
            f"\n【{domain}】{n} 部 → {len(groups)} 组 · 最大组 {max(sizes)} 部 · "
            f"期望扫描 {flat:.1f} → {grouped_cost:.1f} 行"
            f"（{(grouped_cost - flat) / flat:+.0%}）"
        )
        for name, g in groups:
            mark = " ⚠️未登记" if name == "未分类" else ""
            print(f"    {name:<8} {len(g):>2} 部{mark}")
            if name == "未分类":
                problems += len(g)
                for s in g:
                    print(f"        · {s['spec_code']}  {s['spec_name']}")

    # 分类表里有、语料里没有的（拼写错或规范下线）
    norm_corpus = {normalize_spec_code(c) for c in all_codes}
    stale = [k for k in SUBCATEGORY_BY_SPEC if normalize_spec_code(k) not in norm_corpus]
    if stale:
        problems += len(stale)
        print(f"\n⚠️ 分类表有、语料无（{len(stale)} 项，疑似拼写错）：")
        for k in stale:
            print(f"    · {k} → {SUBCATEGORY_BY_SPEC[k]}")

    # 分类名未进 SUBCATEGORY_ORDER → 不会按预期顺序展示
    ordered = {n for names in SUBCATEGORY_ORDER.values() for n in names}
    orphan = sorted(set(SUBCATEGORY_BY_SPEC.values()) - ordered)
    if orphan:
        problems += len(orphan)
        print(f"\n⚠️ 分类名未登记到 SUBCATEGORY_ORDER（{len(orphan)} 个，展示顺序不可控）：")
        for name in orphan:
            print(f"    · {name}")

    # 覆盖率
    covered = sum(1 for c in all_codes if get_subcategory(c))
    subdivided_codes = sum(
        len(specs)
        for domain, specs in corpus.items()
        if is_subdivided(domain, len(specs))
    )
    # 导航成本汇总（按域规范数加权 —— 大域被查得多，权重应更大）
    total_n = sum(n for _, n, _, _ in cost_rows)
    w_flat = sum(n * f for _, n, f, _ in cost_rows) / max(total_n, 1)
    w_grouped = sum(n * g for _, n, _, g in cost_rows) / max(total_n, 1)
    print("\n" + "-" * 72)
    print("导航成本（期望扫描行数，按域规范数加权）")
    print(f"  平铺 {w_flat:.1f} 行 → 二级细分 {w_grouped:.1f} 行 "
          f"（{(w_grouped - w_flat) / w_flat:+.0%}）")

    print("\n" + "-" * 72)
    print(f"语料 {len(all_codes)} 部；细分域覆盖 {subdivided_codes} 部；已登记二级分类 {covered} 部")
    print(f"细分域覆盖率：{covered}/{subdivided_codes} = {covered / max(subdivided_codes, 1):.1%}")
    print("审计结果：" + ("✅ 无问题" if problems == 0 else f"❌ {problems} 处待处理"))
    return 0 if problems == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

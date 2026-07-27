"""一次性脚本：实测 RAG 单次查询的 TTFT / 总时延 / 输出量，估算成本。

用法（需先停后端释放 Qdrant 锁）：
    python -m scripts.perf_probe

输出：逐条 + P50/P95/mean 聚合。tokens_out 为流式块计数（≈ 输出 token，口径标注）。
"""

from __future__ import annotations

import statistics
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.rag.pipeline import run_rag_sync  # noqa: E402

QUERIES = [
    "居住区配套幼儿园的服务半径不应大于多少米？",
    "居住区人均公共绿地面积的最低要求？",
    "城市居住区的绿地率要求是多少？",
    "幼儿园活动室的使用面积要求？",
    "住宅卧室的最小使用面积是多少？",
    "养老设施居室的使用面积要求？",
    "托儿所、幼儿园的服务半径要求？",
    "城市道路绿化的种植设计标准？",
    "城市公园绿地的服务半径要求？",
    "城市道路行道树的种植间距要求？",
    "防火墙的耐火极限要求是多少？",
    "高层建筑消防车道的最小宽度要求？",
    "安全出口的疏散距离规定？",
    "城市综合管廊内天然气管道如何敷设？",
    "城市道路照明的评价指标有哪些？",
    "城市综合管廊的运行维护有哪些要求？",
    "城市轨道交通区间隧道的温度设计要求？",
    "建筑抗震设防烈度如何确定？",
    "幼儿园建筑的活动单元应如何布置？",
    "公园绿地的乔木种植比例要求？",
    "防火墙上不应开设门窗洞口的规定？",
    "居住区配套设施的设置规定？",
]


def run_one(q: str) -> tuple[int, int, int] | None:
    ttft = total = tok = None
    for evt in run_rag_sync(q):
        if evt["type"] == "done":
            d = evt["data"]
            ttft, total, tok = d["ttft_ms"], d["total_ms"], d["tokens_out"]
    if total and total > 0:  # 排除兜底（total=0）
        return int(ttft or 0), int(total), int(tok or 0)
    return None


def pct(xs: list[int], p: float) -> int:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * p))]


def main() -> None:
    rows = []
    print(f"实测 {len(QUERIES)} 条查询（真实 RAG 全链路）...\n")
    for q in QUERIES:
        try:
            r = run_one(q)
        except Exception as e:
            print(f"  ERR {q[:24]}: {str(e)[:60]}")
            continue
        if r:
            rows.append(r)
            print(f"  ttft {r[0]:>5}ms | 总 {r[1]:>6}ms | 输出 {r[2]:>4} 块 | {q[:24]}")
        else:
            print(f"  （兜底/无结果，跳过）{q[:24]}")

    if not rows:
        print("无有效样本")
        return
    ttfts = [r[0] for r in rows]
    totals = [r[1] for r in rows]
    toks = [r[2] for r in rows]
    print(f"\n=== 聚合（n={len(rows)} 条答出，已排除兜底）===")
    print(f"TTFT 首字  : P50 {pct(ttfts, .5)}ms · P95 {pct(ttfts, .95)}ms · mean {statistics.mean(ttfts):.0f}ms")
    print(f"总时延     : P50 {pct(totals, .5)}ms · P95 {pct(totals, .95)}ms · mean {statistics.mean(totals):.0f}ms")
    print(f"输出量     : mean {statistics.mean(toks):.0f} 块（≈输出 token）· max {max(toks)}")


if __name__ == "__main__":
    main()

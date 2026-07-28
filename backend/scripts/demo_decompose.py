"""演示：查询分解 Agent 对「发散/复合题」的价值（不分解 vs 分解，真实生成对比）。

用途：证明分解的价值在**生成完整性**（答得全），而非 retrieval Hit@5——
后者用单条 GT 测不出「多子话题覆盖」（详见 docs/devlog/2026-W7_query_decompose.md）。

用法（需先停后端释放 Qdrant 锁）：
    python -m scripts.demo_decompose
    python -m scripts.demo_decompose "自定义发散问题？"

对每个问题打印：
    - 分解出的子问题
    - 不分解 vs 分解 各喂给 LLM 的 chunk（spec + clause + 域 → 看覆盖了哪些子话题）
    - 两版真实生成答案（看完整性差异）
"""

from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.core.prompts import SYSTEM_PROMPT_MAIN, build_user_prompt  # noqa: E402
from app.rag.embedder import embed_one  # noqa: E402
from app.rag.generator import stream_chat_sync  # noqa: E402
from app.rag.query_decomposer import (  # noqa: E402
    decompose_query,
    retrieve_decomposed_chunks,
)
from app.rag.reranker import rerank  # noqa: E402
from app.rag.retriever import dedup_results, search  # noqa: E402

DEFAULT_QUERIES = [
    "城市新区的道路建设有什么规范要求？",
    "高层办公建筑的耐火等级和防火分区面积要求？",
]


def _generate(query: str, payloads: list[dict]) -> str:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT_MAIN},
        {"role": "user", "content": build_user_prompt(query, payloads)},
    ]
    out: list[str] = []
    for ev in stream_chat_sync(messages):
        if ev["type"] == "token":
            out.append(ev["data"])
        elif ev["type"] == "done":
            break
    return "".join(out)


def _show_chunks(tag: str, payloads: list[dict]) -> None:
    print(f"\n{'=' * 64}\n{tag} — 喂给 LLM 的 {len(payloads)} 条 chunk：")
    for p in payloads:
        head = (p.get("text") or "").replace("\n", " ")[:34]
        print(f"  · {p.get('spec_code')} {p.get('clause')} [{p.get('domain')}] {head}")


def demo(query: str) -> None:
    print(f"\n{'#' * 64}\n问题：{query}")

    # 不分解：单次检索
    qvec = embed_one(query)
    off = [
        r["payload"]
        for r in rerank(query, dedup_results(search(qvec, top_k=40))[:20], top_k=5, min_score=0.1)
    ]

    # 分解
    subs = decompose_query(query)
    if len(subs) > 1:
        print(f"分解子问题：{subs[1:]}")
        on = retrieve_decomposed_chunks(subs[1:], per_sub_top=2)
    else:
        print("（判定为单一问题，不拆）")
        on = off

    _show_chunks("【不分解】", off)
    _show_chunks("【分解】", on)
    print(f"\n{'-' * 64}\n【不分解】答案：\n{_generate(query, off)}")
    print(f"\n{'-' * 64}\n【分解】答案：\n{_generate(query, on)}")


def main() -> None:
    queries = sys.argv[1:] or DEFAULT_QUERIES
    for q in queries:
        demo(q)


if __name__ == "__main__":
    main()

"""W7 D10：用 LLM 生成式校对发现新规范的系统性 OCR 错字。

启示 63：LLM「verify（判对错）」无效（100% uncertain）。
本脚本改用「生成式校对」：让 LLM 直接输出 错字=>正字，更能揪出同形替换错
（管廊→管庵、粒径→被径），这类启发式扫不出（都是合法字）。

系统性错字会跨多条 chunk 重复出现，故采样高价值 chunk 即可发现。
聚合按出现频次排序 → 人工过目 → 高频无歧义的加进 fix_chunks_ocr.FIX_MAP。

用法：
    python -m scripts.discover_ocr_errors --domains 市政,结构 --sample 60
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

from openai import OpenAI

from app.core.config import settings

_HERE = Path(__file__).resolve().parent
CHUNKS_DIR = _HERE.parent / "data" / "chunks"

PROOFREAD_PROMPT = """你是规范文本 OCR 校对专家。下面是从设计规范 PDF 提取的一段文字，可能含 OCR 错字（尤其是被错认成另一个合法汉字的，如「管廊」错成「管庵」、「粒径」错成「被径」）。

请只输出你【高度确信】的错字订正，每行一个，格式：错字=>正字
- 只订正明显的 OCR 错字，不要改专业术语、数字、标点
- 不确定的不要输出
- 没有错字则输出：NONE

规范条文：
{text}"""

# 只接受 1-3 字的同长替换（系统性 OCR 错字特征），过滤 LLM 瞎改
_PAIR_RE = re.compile(r"^([一-鿿]{1,3})=>([一-鿿]{1,3})$")


def _load_new_spec_chunks(domains: set[str]) -> list[dict]:
    chunks = []
    for jf in sorted(CHUNKS_DIR.glob("*.json")):
        if jf.name.startswith("_"):
            continue
        arr = json.loads(jf.read_text(encoding="utf-8"))
        if arr and isinstance(arr[0], dict) and arr[0].get("domain") in domains:
            chunks.extend(c for c in arr if isinstance(c, dict))
    return chunks


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--domains", default="市政,结构")
    ap.add_argument("--per-spec", type=int, default=3)
    ap.add_argument("--sample", type=int, default=60)  # 兼容保留，未用
    args = ap.parse_args()

    domains = set(args.domains.split(","))
    chunks = _load_new_spec_chunks(domains)
    # per-spec 均匀采样：每部挑 per_spec 条长度适中的 chunk（评估每部错字率）
    by_spec: dict[str, list[dict]] = {}
    for c in chunks:
        if 60 <= len(c.get("text", "")) <= 400:
            by_spec.setdefault(c["spec_code"], []).append(c)
    sample = []
    for code, lst in by_spec.items():
        lst.sort(key=lambda c: c.get("is_mandatory", False), reverse=True)
        sample.extend(lst[: args.per_spec])
    print(f"目标域 {domains}：{len(by_spec)} 部 / {len(chunks)} chunks，per-spec 采样 {len(sample)} 条\n")

    client = OpenAI(api_key=settings.deepseek_api_key, base_url=settings.deepseek_base_url)
    pair_count: Counter = Counter()
    examples: dict[str, str] = {}
    spec_err: Counter = Counter()  # 每部规范的错字 chunk 数（烂扫识别）
    spec_seen: Counter = Counter()

    for i, ck in enumerate(sample, 1):
        spec_seen[ck["spec_code"]] += 1
        text = ck.get("text", "")[:500]
        try:
            resp = client.chat.completions.create(
                model=settings.deepseek_model,
                messages=[{"role": "user", "content": PROOFREAD_PROMPT.format(text=text)}],
                temperature=0.0, timeout=30,
            )
            out = resp.choices[0].message.content.strip()
        except Exception as e:
            print(f"  [{i}] err: {e}")
            continue
        if out.upper().startswith("NONE"):
            continue
        n_pairs = 0
        for line in out.splitlines():
            m = _PAIR_RE.match(line.strip())
            if m and m.group(1) != m.group(2) and m.group(1) != "错字":  # 排除 LLM 抄 prompt 格式
                pair = f"{m.group(1)}=>{m.group(2)}"
                pair_count[pair] += 1
                examples.setdefault(pair, ck["spec_code"])
                n_pairs += 1
        if n_pairs:
            spec_err[ck["spec_code"]] += 1

    print(f"\n=== 系统性候选（频次 ≥2，可加字典）===")
    sys_pairs = [(p, n) for p, n in pair_count.most_common() if n >= 2]
    for pair, n in sys_pairs:
        err, fix = pair.split("=>")
        print(f"  {err}→{fix}  ×{n}  ({examples[pair]})")
    print(f"  → {len(sys_pairs)} 种系统性；另有 {sum(1 for _,n in pair_count.items() if n==1)} 种 freq=1（多为烂扫随机错，字典治不了）")

    print(f"\n=== 每部规范 错字 chunk 占比（识别烂扫 PDF）===")
    for code in sorted(spec_seen, key=lambda c: spec_err[c]/max(spec_seen[c],1), reverse=True):
        seen = spec_seen[code]; err = spec_err[code]
        if seen >= 2:
            print(f"  {err}/{seen} ({100*err/seen:.0f}%) {code}")


if __name__ == "__main__":
    main()

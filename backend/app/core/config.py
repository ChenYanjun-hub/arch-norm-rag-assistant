"""全局配置：环境变量、常量、不变量。

所有密钥、URL、可调参数都集中在此处，禁止散落到业务代码里硬编码（CLAUDE.md C.2）。
依赖 python-dotenv 自动加载 backend/.env。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# backend/ 根目录
BACKEND_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = BACKEND_ROOT / ".env"

# 即便 .env 缺失也不报错，让骨架阶段能跑通
load_dotenv(dotenv_path=ENV_PATH, override=False)


@dataclass(frozen=True)
class Settings:
    """应用配置单例。所有字段从环境变量加载。"""

    # LLM（主：DeepSeek，备：通义千问 Max）—— CLAUDE.md 附录已锁定，不可换
    deepseek_api_key: str = os.getenv("DEEPSEEK_API_KEY", "")
    deepseek_base_url: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    deepseek_model: str = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    qwen_api_key: str = os.getenv("QWEN_API_KEY", "")
    qwen_base_url: str = os.getenv(
        "QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    qwen_model: str = os.getenv("QWEN_MODEL", "qwen-max")

    # 向量库（Qdrant，锁定）
    # QDRANT_URL：HTTP(S) URL → 远程服务模式；为空 → 本地文件嵌入模式（开发期推荐）
    qdrant_url: str = os.getenv("QDRANT_URL", "")
    qdrant_api_key: str = os.getenv("QDRANT_API_KEY", "")
    qdrant_collection: str = os.getenv("QDRANT_COLLECTION", "specs_v1")
    # 本地文件模式的存储路径
    qdrant_local_path: str = os.getenv(
        "QDRANT_LOCAL_PATH", str(BACKEND_ROOT / "data" / "qdrant_local")
    )

    # 元数据库（SQLite，锁定，直接用 sqlite3）
    sqlite_path: str = os.getenv(
        "SQLITE_PATH", str(BACKEND_ROOT / "data" / "metadata.db")
    )

    # 数据目录
    specs_dir: str = str(BACKEND_ROOT / "data" / "specs")
    chunks_dir: str = str(BACKEND_ROOT / "data" / "chunks")
    eval_dir: str = str(BACKEND_ROOT / "data" / "eval")

    # 日志
    log_level: str = os.getenv("LOG_LEVEL", "INFO")

    # CORS：本地前端默认端口
    cors_allow_origins: list[str] = field(
        default_factory=lambda: os.getenv(
            "CORS_ALLOW_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
        ).split(",")
    )


# RAG 算法硬约束（CLAUDE.md E 模块，未经讨论不可改）
CHUNKING_RULES: dict[str, object] = {
    "primary_unit": "条款",
    "max_chunk_size": 800,
    "min_chunk_size": 50,
    "table_separate": True,
    "formula_separate": True,
    "preserve_metadata": True,
}

RETRIEVAL_CONFIG: dict[str, object] = {
    "top_k_rough": 20,
    "top_k_rerank": 5,
    "min_relevance": 0.3,
    "filter_by_domain": True,
}

# 性能预算（CLAUDE.md E.5）
LLM_TIMEOUT_SECONDS = 30
LLM_MAX_RETRIES = 1

# Reranker 开关：默认开（提升召回质量），可在 .env 关
RERANK_ENABLED = os.getenv("RERANK_ENABLED", "true").lower() in ("1", "true", "yes")
RERANK_MIN_SCORE = float(os.getenv("RERANK_MIN_SCORE", "0.1"))

# Multi-query 改写（W3 D2 加）：默认关 ⚠️ W4 D4 修订
# W3 D2 在 v2 评测集报告 "+2.6pp loose"，作为 SUCCESS 启用了 4 天。
# W4 D4 在 v3.1（修对 spec 错位）评测集上 6 组合矩阵复测：
#   A (mq=on, rk=on, hyb=on):  strict 32.3% / loose 80.6%
#   B (mq=off, rk=on, hyb=on): strict 32.3% / loose 80.6% （完全同 A）
#   → W3 D2 "+2.6pp" 100% 是 v2 评测集瑕疵造成的假阳性
#   → 在 v3.1 上 0 改善 + 时延 ×4，关默认是正确决策
# 详见 docs/eval/2026-W4_eval_v3_1_report.md + AIPM v5.1 启示 39（假阳性更隐蔽）
# 保留代码完整 + env flag 一键启用（启示 24：失败实验标准处置）
MULTI_QUERY_ENABLED = os.getenv("MULTI_QUERY_ENABLED", "false").lower() in (
    "1",
    "true",
    "yes",
)
# 改写超时：超过则降级走单 query（保 TTFT 不爆 3s SLA）
MULTI_QUERY_TIMEOUT_SECONDS = float(os.getenv("MULTI_QUERY_TIMEOUT_SECONDS", "3.0"))
# 期望的变体数（不含原 query），LLM 拿不到那么多时按实际返回
MULTI_QUERY_MAX_VARIANTS = int(os.getenv("MULTI_QUERY_MAX_VARIANTS", "3"))
# RRF 融合的 k 常数（业界标准 60）
MULTI_QUERY_RRF_K = int(os.getenv("MULTI_QUERY_RRF_K", "60"))

# Reranker 输入候选数（W3 D4 加）⚠️ 默认 20 = baseline
# W3 D4 4 组合实验：
#   ck=20, pf=text_only  : Hit@5 loose 50.0% (baseline)
#   ck=30, pf=text_only  : 47.4% (-2.6pp 劣化，候选稀释)
#   ck=20, pf=clause_text: 47.4% (-2.6pp 劣化)
#   ck=30, pf=clause_text: 50.0% (持平但时延 +50%)
# strict 4 个组合全部 2.6% 不动 → reranker 黑盒，参数调整无法解锁 strict
# 默认保持 20（baseline 最优），保留 env 翻 30 用于未来对照
RERANK_CANDIDATE_K = int(os.getenv("RERANK_CANDIDATE_K", "20"))

# Reranker 输入 passage 格式（W3 D4 加）⚠️ 默认 text_only = baseline
# 4 组合实验同上，默认 text_only 是 baseline 最优
# 保留 clause_text / rich 实现，未来换 reranker 模型时可重新评估
# 可选：
#   "text_only"   - 只 chunk.text（W3 D4 baseline 最优）
#   "clause_text" - "{clause} {text}"（理论上更含语义，实测劣化）
#   "rich"        - "<规范>{spec_name}</规范> <条文>{clause}</条文> {text}"
RERANK_PASSAGE_FORMAT = os.getenv("RERANK_PASSAGE_FORMAT", "text_only")

# Hybrid 检索（W3 D3 加）：默认关 ⚠️
# 实测在 v2 评测集（38 条）上：
#   hyb=OFF: Hit@5 loose = 50.0%
#   hyb=ON:  Hit@5 loose = 47.4% (-2.6pp)
#   规划域劣化 -7.7pp（典型 case Q021 "280m 服务半径 8 班幼儿园 符合吗"）
# 根因：评测集偏"问具体数值是否合规"型查询，BM25 召回的"含数值的非答案条款"
# 挤掉了 BGE-M3 语义关联到的"上限规定"。详见 docs/devlog/2026-05-31_evening_W3D3.md
# 保留实现（不同评测集 / 关键词型查询场景可能有效），默认关
HYBRID_ENABLED = os.getenv("HYBRID_ENABLED", "false").lower() in (
    "1",
    "true",
    "yes",
)
# BM25 单路召回数：与向量路径同 top_k（rrf_fuse 会自动按 rank 融合）
HYBRID_BM25_TOP_K = int(os.getenv("HYBRID_BM25_TOP_K", "20"))

settings = Settings()

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

# Multi-query 改写（W3 D2 加）：默认开
# 解决 BGE-M3 在专业规范文本上的语义偏（详见 docs/design/retrieval_v2.md）
MULTI_QUERY_ENABLED = os.getenv("MULTI_QUERY_ENABLED", "true").lower() in (
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

settings = Settings()

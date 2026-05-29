"""FastAPI 应用入口。

启动方式：
    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

模块职责：
    - 注册 API 路由（/api/chat、/api/spec、/api/eval、/api/health）
    - 配置 CORS、全局异常处理、日志
    - 应用启动/关闭时的资源初始化（向量库连接、SQLite 等）

目前为骨架阶段，仅提供 /api/health 健康检查端点，用于验证环境可用。
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="建景规规范知识问答助手 API",
    version="0.0.1-skeleton",
    description="RAG 智能规范查询服务（MVP 骨架阶段）",
)

# CORS：MVP 期间允许本地前端访问；生产部署前必须收紧
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    """健康检查端点。返回服务状态。"""
    logger.info("[health] ping")
    return {"status": "ok", "version": app.version}


# ── 路由注册 ────────────────────────────────────
from app.api import chat as chat_api  # noqa: E402
from app.api import spec as spec_api  # noqa: E402

app.include_router(chat_api.router, prefix="/api")
app.include_router(spec_api.router, prefix="/api")

# TODO(W4): 注册 eval 路由
# from app.api import eval as eval_api
# app.include_router(eval_api.router, prefix="/api")

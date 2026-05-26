# 准备日 To-Do · 开发启动前一天

> 完成这些，第二天就能直接进入 W1 数据准备 + 骨架开发，零空转。
> 预计总时长 6 小时（分上午 / 下午 / 晚上 3 段）

---

## 上午 · 9:00-12:00 · 账号与基础设施（3 小时）

### 1.1 申请 DeepSeek API Key（30 分钟）
- 访问 https://platform.deepseek.com
- 注册账号（手机号即可）
- 充值 10 元（足够 MVP 阶段使用）
- API Keys 页面创建 Key，**保存到本地 .env 文件**
- 备注：DeepSeek V3 价格约 ¥1/百万 tokens，10 元能用很久

### 1.2 申请通义千问 API Key（备用，30 分钟）
- 访问 https://bailian.console.aliyun.com
- 阿里云账号登录（已有可跳过注册）
- 开通"百炼大模型"服务
- 创建 API Key，**也保存到 .env**
- 用途：DeepSeek 偶发不稳定时的兜底切换

### 1.3 购买阿里云服务器（45 分钟）
- 配置：4 核 8G **突发性能 t6 实例** · Ubuntu 22.04 LTS
- 月付约 ¥150-300（具体看地域和优惠活动）
- 系统盘：40GB SSD（够用）
- 公网带宽：5Mbps（演示场景够用）
- 配置安全组：开放 80 / 443 / 22 端口
- **登录测试**：`ssh root@<公网IP>`

### 1.4 注册 Vercel 账号（15 分钟）
- 访问 https://vercel.com
- 用 GitHub 登录（最方便）
- 用途：前端 React 应用部署，免费额度足够个人项目

### 1.5 本地环境检查（30 分钟）
```bash
python --version   # 需 3.10+
node --version     # 需 18+
docker --version   # 需安装
git --version      # 应该已有
```
缺啥装啥。Mac 推荐用 `brew`，Win 推荐用官方安装包。

### 1.6 创建项目仓库（30 分钟）
- GitHub 创建私有仓库：`prd-rag` 或 `jianjinggui-assistant`
- 本地 `git clone` 下来
- 创建基础目录结构：
```
/backend     # FastAPI 后端
/frontend    # React 前端
/data        # 规范 PDF + 元数据
/eval        # 评测集
/docs        # PRD 等文档
.gitignore   # 忽略 .env / node_modules / __pycache__
README.md    # 项目说明
```

---

## 下午 · 14:00-17:00 · 规范数据收集（3 小时）

### 2.1 国标公开系统下载（90 分钟）
访问 https://openstd.samr.gov.cn

下载以下 12 部（按搜索框输入标准号搜索）：

| 类别 | 标准号 | 全称 |
|---|---|---|
| 规划 | GB 50180-2018 | 城市居住区规划设计标准 |
| 规划 | GB 50137-2011 | 城市用地分类与规划建设用地标准 |
| 建筑 | GB 50352-2019 | 民用建筑设计统一标准 |
| 建筑 | GB 50096-2011 | 住宅设计规范 |
| 建筑 | GB 50099-2011 | 中小学校设计规范 |
| 消防 | GB 50016-2014 | 建筑设计防火规范 |
| 消防 | GB 51251-2017 | 建筑防烟排烟系统技术标准 |
| 结构 | GB 50011-2010 | 建筑抗震设计规范 |
| 结构 | GB 50068-2018 | 建筑结构可靠性设计统一标准 |
| 景观 | GB 51192-2016 | 公园设计规范 |
| 景观 | CJJ/T 91-2017 | 风景园林基本术语标准 |

### 2.2 北京地标补充（30 分钟）
- 访问北京住建委官网或"北京市市场监督管理局"
- 搜索 DB11/1224-2023 城市居住公共服务设施规划设计指标
- 下载 PDF

### 2.3 文件命名规范化（30 分钟）
统一文件名格式：
```
GB50180-2018_城市居住区规划设计标准.pdf
GB50137-2011_城市用地分类与规划建设用地标准.pdf
...
```
放到 `/data/specs/` 目录。

### 2.4 建立元数据 CSV（30 分钟）
创建 `/data/spec_metadata.csv`：
```csv
spec_code,name,year,category,file_path,page_count,mandatory
GB50180-2018,城市居住区规划设计标准,2018,规划,GB50180-2018_城市居住区规划设计标准.pdf,68,true
GB50137-2011,城市用地分类与规划建设用地标准,2011,规划,GB50137-2011_城市用地分类与规划建设用地标准.pdf,52,true
...
```

---

## 晚上 · 20:00-21:30 · 开发环境与首个 Hello World（1.5 小时）

### 3.1 后端骨架（30 分钟）
```bash
cd backend
# 用 uv 或 venv 创建虚拟环境
python -m venv .venv
source .venv/bin/activate   # Win: .venv\Scripts\activate

# 安装核心依赖
pip install fastapi uvicorn[standard] langchain langchain-openai \
            qdrant-client pymupdf python-dotenv
```

创建 `main.py`：
```python
from fastapi import FastAPI
app = FastAPI()

@app.get("/")
def root():
    return {"message": "建景规规范助手 API"}
```

测试：`uvicorn main:app --reload`，浏览器访问 http://127.0.0.1:8000 看到 JSON 即成功。

### 3.2 前端骨架（30 分钟）
```bash
cd ..
pnpm create vite@latest frontend -- --template react-ts
cd frontend
pnpm install
pnpm install -D tailwindcss postcss autoprefixer
npx tailwindcss init -p
pnpm dev
```

浏览器访问 http://localhost:5173 看到 React 默认页面即成功。

### 3.3 测通 LLM 调用（30 分钟）
在 backend 目录创建 `test_llm.py`：
```python
import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com"
)

stream = client.chat.completions.create(
    model="deepseek-chat",
    messages=[{"role": "user", "content": "你好，请简单介绍一下自己"}],
    stream=True,
)

for chunk in stream:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="", flush=True)
print()
```

运行：`python test_llm.py`

**看到 DeepSeek 流式输出回答 = 今天大成功！**

---

## ✅ 今日结束验收

下班前确认：
- [ ] 后端能 hello world，能调通 DeepSeek API
- [ ] 前端 Vite + React 能 dev 跑起来
- [ ] 12 部规范 PDF 都在本地 `/data/specs/`
- [ ] 元数据 CSV 已建立
- [ ] 阿里云服务器能 SSH 登录
- [ ] GitHub 私有仓库已建立 + 推送了初始代码

满足以上 6 项 = 准备日完美，明天 W1 开发顺利启动。

---

## 💡 一些温馨提示

1. **别追求完美**：今天目标是"能跑起来"，不是"写得漂亮"。代码风格、目录结构以后可以重构。
2. **API Key 安全**：永远不要把 .env 推到 GitHub。`.gitignore` 加上 `.env` 是第一件事。
3. **阿里云费用**：突发性能 t6 实例平时低负载省钱，但**性能积分用完会限速**。如果担心，可以选普通 c6e 实例。
4. **遇到问题别死磕**：单人项目时间紧，遇到 1 小时解决不了的事，先用替代方案绕过。比如 PDF 解析有问题，可以先用 PyMuPDF 简单提取文本，到 W2 再深度优化。
5. **建议建立"问题日志"**：每天结束前记下遇到的坑，便于复盘和写课程作业报告时用。

# 知渊 (ZhiYuan) — Agentic RAG 智能知识库

基于 **Agentic RAG** 架构的智能知识库检索平台。上传文档后，通过混合检索（稠密向量 + 稀疏向量）与 LLM Agent 自动规划、检索、推理，精准回答你的问题。

## 功能特性

- **多格式文档解析** — 支持 PDF、Word (.docx)、Excel (.xlsx)
- **三级滑动窗口分块** — L1(1200字) / L2(600字) / L3(300字) 层级分块，叶子向量化，父级自动合并
- **混合检索** — 稠密向量 (BGE-M3) + 稀疏向量 (BM25)，RRF 融合排序
- **智能重排序** — Jina Reranker v3 对候选结果二次精排
- **Agent 自主规划** — LangChain Agent 驱动，自主选择检索策略、调用工具
- **查询扩展** — 检索质量不足时自动触发退步问题 / HyDE / 复杂策略重写
- **实时 Web 搜索** — 知识库无结果时自动联网补充（Tavily）
- **流式对话** — SSE 实时推送，打字机效果 + RAG 检索过程可视化
- **用户认证** — JWT 登录/注册，管理员 + 普通用户双角色
- **文档管理** — 批量上传/删除，实时进度跟踪

## 架构概览

```
浏览器 (Vue 3 SPA) ──SSE──▶ FastAPI 后端 ──▶ LangChain Agent
                                    │              │
                                    │              ├── search_knowledge_base (RAG)
                                    │              ├── search_web (Tavily)
                                    │              └── get_weather (高德)
                                    │
                                    ├── PostgreSQL (用户/会话/父级分块)
                                    ├── Redis (缓存)
                                    └── Milvus (稠密 + 稀疏向量)
```

### RAG 管道

```
用户查询 → 混合检索 (Milvus) → Jina 重排序 → 自动合并父块
                                                    │
                                              LLM 相关性评分
                                               │         │
                                            相关       不相关
                                              │         │
                                              ▼         ▼
                                          生成回答   查询重写 (退步/HyDE/复杂)
                                                        │
                                                   扩展检索 → 生成回答
```

## 技术栈

| 层 | 技术 |
|---|------|
| 后端框架 | FastAPI + Uvicorn |
| Agent 框架 | LangChain + LangGraph |
| 大语言模型 | Qwen3-Max / Qwen3.6-Flash (DashScope) |
| 向量模型 | BAAI/bge-m3 (1024维) |
| 向量数据库 | Milvus 2.5 (HNSW + 稀疏倒排索引) |
| 关系数据库 | PostgreSQL 15 |
| 缓存 | Redis 7 |
| 重排序 | Jina Reranker v3 |
| 前端 | Vue 3 + Phosphor Icons + marked + highlight.js |
| 容器化 | Docker Compose |

## 快速开始

### 1. 克隆项目

```bash
git clone https://github.com/LXY666-bit/ZhiYuan.git
cd ZhiYuan
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，填入你的 API 密钥：

- `ARK_API_KEY` — [阿里云 DashScope](https://dashscope.console.aliyun.com/apiKey)
- `RERANK_API_KEY` — [Jina AI](https://jina.ai/)
- `TAVILY_API_KEY` — [Tavily](https://tavily.com/)（网页搜索用，可选）
- `AMAP_API_KEY` — [高德开放平台](https://lbs.amap.com/)（天气查询用，可选）

### 3. 安装依赖

本项目使用 [uv](https://docs.astral.sh/uv/) 管理 Python 依赖：

```bash
uv sync
```

### 4. 启动基础设施

```bash
docker-compose up -d
```

这会启动 PostgreSQL、Redis、Milvus、etcd、MinIO。首次下载镜像需要几分钟。

### 5. 启动后端

```bash
uv run python backend/app.py
```

### 6.启动前端

访问 **http://localhost:8000**

### 7. 注册管理员

1. 前端页面选择"注册"
2. 角色选"管理员"
3. 填入 `.env` 中设置的 `ADMIN_INVITE_CODE`
4. 登录后即可上传文档、管理用户

## 项目结构

```
ZhiYuan/
├── backend/
│   ├── app.py              # FastAPI 入口
│   ├── api.py              # REST API 路由
│   ├── agent.py            # LangChain Agent + 对话存储
│   ├── tools.py            # Agent 工具（知识库/网络/天气）
│   ├── rag_pipeline.py     # LangGraph RAG 管道
│   ├── rag_utils.py        # 检索/重排序/自动合并/查询扩展
│   ├── embedding.py        # BGE-M3 稠密 + BM25 稀疏向量
│   ├── milvus_client.py    # Milvus 连接与混合检索
│   ├── milvus_writer.py    # 向量批量写入
│   ├── document_loader.py  # 文档解析 + 三级分块
│   ├── parent_chunk_store.py  # 父级分块 PostgreSQL 存储
│   ├── upload_jobs.py      # 上传/删除任务进度管理
│   ├── models.py           # SQLAlchemy ORM 模型
│   ├── schemas.py          # Pydantic 请求/响应模型
│   ├── auth.py             # JWT 认证
│   ├── database.py         # SQLAlchemy 配置
│   └── cache.py            # Redis 缓存
├── frontend/
│   ├── index.html          # Vue 3 SPA
│   ├── script.js           # 应用逻辑
│   └── style.css           # 玻璃拟态设计系统
├── docker-compose.yml      # PostgreSQL + Redis + Milvus + etcd + MinIO
├── pyproject.toml          # Python 依赖
├── .env.example            # 环境变量模板
└── README.md
```

## API 端点

### 认证
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/auth/register` | 注册 |
| POST | `/auth/login` | 登录 |
| GET | `/auth/me` | 当前用户信息 |

### 聊天
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/chat` | 非流式对话 |
| POST | `/chat/stream` | SSE 流式对话 |

### 文档管理（管理员）
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/documents` | 文档列表 |
| POST | `/documents/upload/async` | 异步上传 |
| DELETE | `/documents/delete/async/{name}` | 异步删除 |

### 用户管理（管理员）
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/users` | 用户列表 |
| DELETE | `/users/{username}` | 删除用户 |
| PUT | `/users/{username}/role` | 修改角色 |

## License

MIT

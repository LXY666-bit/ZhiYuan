# Research Workbench 上线与恢复手册

本文覆盖「深度研搜」的上线、烟雾验证、受控停止和故障恢复。命令均从 release 根目录执行。
研究工作台复用 canonical Thread / Run / Event / Checkpoint；不要单独启动研究 Run worker。

## 前置条件

- PostgreSQL 已备份，且 API、索引 worker 使用同一 release 与数据库。
- `ARTIFACT_DIR` 与 `RESEARCH_ATTACHMENT_DIR` 指向持久目录；API 与索引 worker 对附件目录具有相同视图。
- 启用任一研究模式的 Web 来源前，通过 Secret 管理器注入 `TAVILY_API_KEY`；Key 不写入数据库、
  Event、日志或前端。
- PostgreSQL、Redis、Milvus、模型控制面和 Answer/Fast/Grader 角色均通过 readiness 检查。

## 迁移和启动

先停止旧 API 与索引 worker，再执行：

```bash
uv sync --frozen
uv run --frozen alembic upgrade head
uv run --frozen python -c \
  "from backend.infra.database import assert_schema_current; assert_schema_current()"
uv run --frozen python -m backend.tools.registry_cli validate
```

迁移 `0019_artifact_store` 和 `0020_research_workbench` 是前向迁移。无法安全 downgrade 时应修复当前
release 并向前发布，不能用旧应用连接新 schema。随后启动索引 worker 和 API：

```bash
uv run --frozen python -m backend.workers.indexing
uv run --frozen python -m backend --host 127.0.0.1 --port 8000
```

Windows 开发机必须通过 `python -m backend` 启动 API；直接 `uvicorn backend.app:app`
会在 ProactorEventLoop 上运行，深度研搜的 psycopg 异步 checkpoint 连接将直接失败。

API lifespan 会启动持久 Research Plan Job Dispatcher。索引 worker 同时领取普通 Index Job 与
Research Attachment Job；二者都必须保持运行。

## 最小烟雾验证

使用测试账号在「深度研搜」完成以下流程：

1. 创建 Quick Project，并确认普通 Thread 列表不出现对应 research Thread。
2. 创建 Plan Job，轮询至 `succeeded`，编辑计划后批准。
3. 从审批响应取得 canonical `run_id`，通过 `/v1/runs/{run_id}/stream` 观察 Event。
4. 确认 Run 进入 terminal 状态，Evidence、Section、Usage 可查询；展开步骤详情，确认自动计划的
   每一步都包含项目勾选的来源，并核对各来源候选、保留、过滤和错误计数。
5. 使用登录态下载 `/api/artifacts/{artifact_id}`，核对最终 Markdown；配置 PDF 时同时核对 PDF。
6. 上传一个研究附件，确认索引成功且另一个 Project 无法检索该附件。

任一模式缺少 `TAVILY_API_KEY` 时必须出现明确降级或失败信息，不得观察到无 Key 静默回退。单个
来源或单章失败可以降级交付，但报告必须披露证据缺口。

若步骤显示知识库降级，Event 中应保留 `research.knowledge_base` 和稳定错误码；若来源健康但没有
结果，应显示“未找到证据”或“候选被过滤”，不能只显示统一的内部错误。同步知识库检索出现
`no running event loop` 表示 release 未包含同步 Run Context 修复，应停止继续重跑并升级 API release。

## 受控停止与恢复

1. 停止接收新的审批和 Plan Job。
2. 正常向 API 发送 SIGTERM，并等待 termination grace。
3. 带有效 Checkpoint 的 research Run 会释放 ownership 并重新排队；重启后由同一 canonical
   `run_id` 恢复。不要手工创建替代 Run。
4. 没有 Checkpoint 的遗留活跃 Run 会以 `RUN_INTERRUPTED` 终结，用户可调用 Research retry/rerun
   创建新 Run。用户主动取消的 Run 保持 `cancelled`，不自动恢复。
5. 索引 worker 重启后会用 lease/fencing 回收过期 Research Attachment Job；成功附件版本才可被审批冻结。

恢复后检查同一 Run 未重复生成 Evidence、Section 或 final Artifact，并确认 Event sequence 连续。

## 故障定位

### Plan Job 长时间 running

- 确认 API lifespan 正常、数据库时间一致，检查 Job lease 是否过期。
- Dispatcher 会回收过期 lease；fencing token 会拒绝旧 worker 的迟到结果。
- Provider 网络重试只由 ProviderExecutor 执行。不要通过反复新建 Job 放大同一次 Provider 故障。

### 附件停在 queued/running

- 确认 `backend.workers.indexing` 存活并通过 readiness。
- 核对 API 与 worker 的 `RESEARCH_ATTACHMENT_DIR` 是否为同一持久目录。
- 仅在 Project 仍为 `draft` 或 `awaiting_approval` 时使用附件 retry；retry 会先清理该附件版本的旧向量。

### Artifact 下载 404

- 404 同时用于不存在与未授权，先核对当前 Tenant、用户、Project 和 Artifact 归属。
- 检查 `ARTIFACT_DIR` 持久卷是否挂载；不要把数据库 `storage_key` 拼成任意本地路径。
- 下载和删除都会重新验证解析路径位于 Artifact 根目录内；路径校验失败时应保留 fail-closed。

## 备份与回滚边界

数据库与 `ARTIFACT_DIR`、`RESEARCH_ATTACHMENT_DIR` 必须作为同一恢复点备份。恢复前先在隔离环境验证
schema 与文件 SHA-256。此次迁移不读取、移动或删除旧知渊数据库、Milvus research collection、
Artifact 文件或运行中 Checkpoint；不要把旧数据目录直接挂载为知渊的新目录。

离线验收使用：

```bash
uv run --frozen python evals/research/run_eval.py --level deterministic --mode all --gated
```

Live 评测会调用真实模型和来源，只有获得明确授权后才按 Quick → Standard → Deep 逐层执行。

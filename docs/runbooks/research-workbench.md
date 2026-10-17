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
2. 创建 Plan Job，轮询至 `completed`；编辑计划后确认审批按钮被禁用，保存新版本后批准。
3. 从审批响应取得 canonical `run_id`，通过 `/v1/runs/{run_id}/stream` 观察 Event。
4. 确认 Run 进入 terminal 状态，Evidence、Section、Usage 可查询；展开步骤详情，确认自动计划的
   每一步都包含项目勾选的来源，并核对各来源候选、保留、过滤和错误计数。
5. 使用登录态下载 `/api/artifacts/{artifact_id}`，核对最终 Markdown；配置 PDF 时同时核对 PDF。
6. 上传一个研究附件，确认索引成功且另一个 Project 无法检索该附件。
7. 确认搜证完成后步骤仍是 running，phase 从 writing 转入 verifying，章节保存后才进入 completed/degraded。较快章节应在其他章节尚未完成时可阅读，最终报告保持计划顺序。
8. 阅读报告并点击 `[E#]`，确认打开同一 Run 的已持久化 Evidence；核验提示区应区分 supported、unsupported、conflicting 和 insufficient。核验服务不可用不能显示“有支持”，引用编号不存在时必须披露。

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

### 模型普通调用成功，但研究规划或审阅报参数错误

- 模型中心的“支持结构化输出”是能力声明，不代表已通过真实 Provider 验证。普通文本或流式请求成功不能证明结构化请求可用。
- 若 Provider 返回 HTTP 400 且指出 `response_format` 类型不支持，检查 API 和评测 worker 是否包含统一 Function Calling 修复；当前结构化调用显式发送 `tools` 和 `tool_choice`，不发送 SDK 默认的 `json_schema`。返回参数仍通过 Pydantic 校验，畸形数据不作为有效计划或结论。
- 更新代码后重启 API 和评测 worker。模型 Assignment 变更只影响新 Run / Evaluation Job；比较新配置应重新生成计划并新建研究。
- 离线回归：`uv run --no-sync pytest -q tests/test_model_structured_output.py`。在线验收需明确授权，验证 Fast/Grader/Evaluator 的真实结构化调用；不通过多次重跑完整研究掩盖确定性参数错误。

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

离线评测现在通过临时 SQLite 数据库、固定资料和 extractive fake model 执行正式审批、Run、研究工作流、Event 与交付物生成；SQLite 事务显式串行化，不能证明 PostgreSQL 锁语义或真实模型质量。引用覆盖按正文段落/列表项计算，排除来源列表；评分 v2 与旧评分结果不可直接比较。网页搜证仍使用受控搜索摘要，本次变更未扩大抓取权限。

## 研究耗时预算

新审批/重新运行冻结 Profile v9，执行 `research-workflow-v6`。默认预算如下，单位为秒：

| 模式 | Run 外部调用预算 | 搜证阶段 | 单个来源 | 单次模型 | 章节写作与审阅总预算 | 核心审阅 | 综合编辑 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Quick | 90 | 25 | 20 | 45 | 60 | 20 | 20 |
| Standard | 180 | 45 | 25 | 60 | 120 | 30 | 30 |
| Deep | 300 | 60 | 30 | 90 | 180 | 40 | 45 |

每次调用同时受冻结 Model Snapshot 的 timeout、阶段预算与 Run 绝对 deadline 约束；取最早 deadline，重试不会重置时间。Standard/Deep 缺口分析另有 15/20 秒上限，写作预留综合编辑预算。预算从 Run 创建开始计算，排队、恢复不会重置；数据库与 Markdown/PDF 保存耗时另计，不承诺页面精确在预算秒数内得到终态。旧冻结任务不会被改写，需重新研究才能获得新预算。

来源在同一阶段有界并行；知识库直接调用现有生产检索阶段而不执行完整问答图。正常章节只需 Writer + 合并审阅两次模型调用；需要修订时追加一次局部写作和一次复核。慢来源记录 `RESEARCH_*_SOURCE_TIMEOUT`，模型超时保留 Provider typed code，结果不得伪装为健康空检索或有支持结论。界面展示服务端冻结预算、耗时、已保存章节和降级提示。

网页搜索使用来源剩余时间的 70%，其余预算用于最多两条已验证搜索 Evidence 的正文补全（每条至多 5 秒）。检查 `fetch_error_code` 可区分补全失败与健康摘要；已识别产品的官方来源要求会过滤镜像和社区文章，官方证据不足时保留缺口。正文数字字数限制不含标题与来源附录，完整章节和核验记录保持可审阅。

聚焦耗时回归：

```powershell
uv run --no-sync pytest -q tests/test_research_latency.py tests/test_research_quality.py tests/test_research_workbench.py
```

Fake model/受控阻塞测试证明并行、调用次数和 deadline/cancellation 行为，不代表真实模型端到端延迟。若要调整预算，应先经明确授权使用同模式、同题、固定模型的 live 评测记录首章保存时间、总耗时、超时率与质量分，不能只追求缩短 timeout。


### 官方资料、版本与输出预算

Profile v8 继续冻结 Writer 输出上限（Quick 1600、Standard 2400、Deep 3200 Token）、审阅 1000、补研 500、综合编辑 1600。已识别的阿里云 DeepSeek V4 关闭额外思考模式，保持冻结模型和 ProviderExecutor 的重试、取消与 deadline。输出被截断时公开 `RESEARCH_OUTPUT_LIMIT`，保留此前保存的章节。

比较任务要求官方资料时，短问题逐对象检索（至多四个拉丁词项），所有调用共用来源预算，不扩大网络并发；部分查询失败时查看来源错误与已保留证据。相同 URL/内容哈希复用引用，内容不同的快照继续保留。文档候选不等于官方认证，URL 中的版本只是线索；没有版本、测试配置或关键条件时报告应披露缺口。前端终态交付提示同时读取持久章节降级和 Run warning，不能仅凭 succeeded 或引用数量判断准确。

已审阅的官方入口覆盖 PostgreSQL、pgvector、Milvus、Qdrant、Redis、RabbitMQ；其他主题仍使用通用来源发现。显式版本参与检索，RabbitMQ 优先对应版本文档。比较目标中的命令名不会挤占已识别产品的查询；持久化、确认、重试、死信等维度使用英文机制词。中文常见维度增加英文检索词，PostgreSQL 未指定历史版本时优先 current 文档；显式历史版本仍保留原检索范围。官方来源要求精确主机和文档路径，GitHub 的用户 Issue 不因同仓库 URL 自动认定为官方文档。


### 选型报告质量

Profile v8 冻结 `reuse_prior_evidence` 和 `verify_synthesis`。事实章节保持有界并行；标题包含“横向比较”“选型”“综合判断/结论/建议/评估”或对应英文决策词的章节，等待事实章节保存，并按计划顺序消费前序持久化 Evidence 与 Claim。自定义计划若需要消费前序结果，应使用这些明确标题。等待不占用章节并发槽，取消会清理等待任务；恢复读取已保存章节，不重置 Run deadline。

比较/选型优先复用同一 Run 的 Evidence，保留原引用编号与内容；复用只接受该 Run 的 Evidence identity，跨 Run/用户传入会拒绝，支持关联仍仅为 supported Claim 建立。前序证据不足不会变成已核验事实，必要时仍可保留条件式建议与验证清单。

资料排序区分官方身份、产品范围、版本线索和是否只有入口/空正文；不匹配材料作为差异线索保留并标注，不能证明目标版本行为。官方文档默认同域最多四条，二手来源最多两条；显式指定的域名配额仍严格遵守。最新命令页的新增版本信息传入审阅，不能笼统地把整页视为旧版可用或全部无效。网页仍只使用受控搜索摘要，不新增任意 URL 抓取。

综合编辑后执行一次事实核验，写作与核验共用原综合阶段绝对预算；不通过或核验服务不可用时记录 `RESEARCH_SYNTHESIS_UNVERIFIED`，移除未经核验的整体推荐，保留核验结果与原章节。章节审阅检查旁支重要事实与必要条件，但受模型判断与证据覆盖限制，不承诺整篇准确。报告使用计划标题并去除重复综合标题，核验提示保留简短原因，完整理由仍在持久 Claim 中。

聚焦回归：`uv run --no-sync pytest -q tests/test_research_decision_quality.py tests/test_research_quality.py tests/test_research_latency.py tests/test_research_evidence_budgets.py tests/test_research_workbench.py`。上线验收还需经明确授权用同题、同模型的新 Run 抽查真实引用，不能用离线通过或 succeeded 代替报告质量核验。旧 final Artifact 不会被改写；重启 API 后新审批使用新 Profile。

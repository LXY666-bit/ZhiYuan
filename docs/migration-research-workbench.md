# 知渊研究工作台迁移实施计划

> 状态：代码实施与离线验收完成；Live 评测待明确授权  
> 日期：2026-09-02  
> 目标代码库：`ZHIYUAN`  
> 关联 ADR：0019、0021、0023、0024、0026

## 1. 目标与边界

以知渊主仓库为唯一目标代码库，将旧版研究计划、多来源检索、Evidence/Claim 核验、缺口补研、分章节 Writer、Critic、Markdown/PDF 产物和研究评测迁入 canonical Thread / Run / Event / Checkpoint 通道。

本次不读取或改变知渊现有数据库、Milvus research collection、Artifact 文件与运行中 Checkpoint，不迁移历史研究数据；普通聊天、RAG Evaluation、Document Version、Auth 与 Capability 行为保持兼容。首个可合并闭环为 Quick，最终完成条件为 Quick/Standard/Deep 和全部离线门禁通过。Live 评测不默认运行。

## 2. 固定架构决策

- 计划生成和审批发生在 Run 之前。Project 审批事务冻结输入并创建 `Run(channel="research")`。
- 唯一公开接口为 `/v1/research/projects`；不提供旧 `/research/tasks` 兼容路由。
- Project 创建时创建专用 `Thread(kind="research")`；普通 Thread 列表默认只返回 `chat`。
- Planner 使用持久 `ResearchPlanJob`，Planner Usage 的 `run_id=null`。
- `RunAgentExecutor` 仅对 `channel="research"` 增加显式分支并调用 `ResearchWorkflowRunner`；不增加通用插件执行框架、研究专用 runtime 或研究专用 SSE。
- LangGraph `thread_id=run_id`。业务表是 Evidence、Claim、Section、Artifact、Usage 的权威来源；Checkpoint 只保存可恢复工作流状态。
- Artifact 是平台通用模块，采用本地原子文件存储及 `GET /api/artifacts/{artifact_id}` 鉴权下载。
- 不增加模型角色：Planner→Fast/Grader，Writer/Revision→Answer，Verifier/Critic→Grader。
- 三种研究模式使用官方 SDK 的受控 Tavily API Key advanced Adapter；缺 Key 时显式降级，不回退无 Key
  搜索。SDK 仅访问固定 Tavily origin；返回来源与后续抓取仍受 URL policy 约束。
- 研究 deterministic/live 评测独立保留，不并入 RAG Evaluation Job。

## 3. Canonical 执行与恢复

```text
ResearchProject(draft)
  -> ResearchPlanJob(Fast/Grader snapshot, run_id=null usage)
  -> immutable ResearchPlan(version N)
  -> approve transaction
       [lock Project + validate Plan/Attachments]
       [freeze Manifest + reserve canonical Run]
  -> RunAgentExecutor(channel=research)
  -> ResearchWorkflowRunner(thread_id=run_id)
  -> business rows + Event Journal/outbox in one transaction
  -> /v1/runs/{run_id}/stream
  -> immutable Markdown/PDF Artifact versions
```

受控停机时，有 Checkpoint 的研究 Run 释放 ownership并重新排队，启动后恢复同一个 Run；无 Checkpoint 的遗留活跃 Run 以 `RUN_INTERRUPTED` 终结并允许 retry。用户取消始终进入 cancelled 终态。节点使用 Run、step、section、evidence 与 artifact 稳定键保证重入幂等。

## 4. 数据模型与约束

迁移 `0019_artifact_store` 创建平台 `artifacts`；`0020_research_workbench` 增加 Thread kind 及以下表：

- `research_projects`
- `research_plans`
- `research_plan_jobs`
- `research_run_manifests`
- `research_steps`
- `research_evidence`
- `research_claims`
- `research_claim_evidence`
- `research_sections`
- `research_usage`
- `research_attachments`
- `research_attachment_jobs`

关键不变量：

- Project 只保存 draft/awaiting_approval/frozen 生命周期；执行状态由最新 canonical Run 投影，禁止双写终态。
- 每个 Project 恰好一个专用 Thread；Thread 的唯一活跃 Run 约束同时约束研究 Run。
- Plan 不可变；编辑创建新版本，审批后不可修改。
- retry/rerun 创建新 Run 与 Manifest，历史 Evidence、Usage、Section、Artifact、Event 不删除。
- Attachment Job 每次 retry 新增记录；审批冻结已成功的附件版本集合。
- Profile 由代码版本化，并完整复制进 Manifest，不增加控制面表。
- 所有研究查询同时过滤 Tenant 与用户；管理员不默认越权。

## 5. API 与契约

正式接口覆盖 Project 创建/列表/详情/删除/clone、Plan Job 创建/查询/取消、Plan 读取/更新/approve、Research retry/rerun、Attachment 上传/列表/删除/retry，以及 Evidence/Claims/Sections/Runs/Metrics/Artifacts 查询。取消与 SSE 复用 canonical Run API。

`contracts/research_api_v1.json` 是后端和前端研究公共类型的来源。Run Event v1 只新增：

- `research.step.updated`
- `research.evidence.updated`
- `research.claims.updated`
- `research.section.updated`
- `research.draft.updated`

继续复用 `retrieval.*`、`usage.updated`、`artifact.created`、`warning.created` 与 `run.*`。Event 只携带稳定身份、状态、计数和版本，不携带正文、URL、查询、内部路径、密钥或异常详情。

## 6. 工作流与资源边界

三模式参数沿用知渊预算：Quick 2–3 步/12 Evidence/1 轮/无补研；Standard 3–5 步/30 Evidence/2 轮/最多 2 缺口；Deep 4–6 步/50 Evidence/2 轮/最多 3 缺口。章节并发从 Run 冻结 Profile 读取，Quick / Standard / Deep 上限分别为 3 / 5 / 6，实际不超过步骤数；Writer 只使用已持久化 Evidence，正式引用统一为稳定 `[E#]`。

Web Research 复用 URL policy、DNS pin、HTTP budget 和 SSRF 防护。Tavily API Key 只进入 transport。附件使用独立 research collection，向量带 Tenant、Project、Attachment 和版本身份，审批冻结完整版本集合，绝不发布到全局 Knowledge Base。

同一 Run 只更新一份 draft Artifact。完成时产生不可变 Markdown/PDF final 版本；单章失败只降级该章，仍可交付。Markdown 编辑创建新 final 版本，并按配置重建 PDF。

## 7. 实施阶段

1. **文档与架构门禁**：本文、Research ADR、CONTEXT、Research AGENTS 与架构测试。
2. **Artifact、Project 与 Plan Job**：两次迁移、Repository、API、持久 Dispatcher、审批原子预留。
3. **Quick canonical Run**：Profile、最小研究图、Event/Checkpoint/Usage、单章 Markdown、恢复与取消。
4. **完整工作流与来源**：Evidence/Claim、补研、分章 Writer、Critic、KB/Web/附件、PDF、Standard/Deep。
5. **前端与评测**：懒加载「深度研搜」、账号作用域 Store、REST Plan Job 轮询、Run Event reducer、20×3 deterministic 评测与 runbook。

## 8. 验收门禁

- Migration：0018→head、Schema current、唯一约束、外键级联，危险 downgrade fail-closed。
- Plan Job：幂等/并发、lease/fencing、orphan recovery、取消、stale result 拒绝、全部尝试 Usage 且 `run_id=null`。
- Ownership：Project/Attachment/Evidence/Artifact 均验证 Tenant 与用户；未授权统一 404。
- Run：审批冻结与 Run/Manifest 同事务、单活跃、retry/rerun/clone、取消竞态、Event 与业务写同事务。
- Recovery：重复节点不重复资源；有 Checkpoint 恢复原 Run，无 Checkpoint interrupted。
- Sources/Writer/Attachment/Artifact：目标锚定、错位门控、域名配额、冲突保留、显式降级、按冻结 Profile 验证章节并发上限、稳定顺序、原子文件、版本链与路径穿越拒绝。
- 最终：完整 pytest/coverage、Ruff、mypy、contract check、registry validate、PostgreSQL Checkpoint 集成、deterministic 60、前端 format/lint/typecheck/unit/build/E2E。

Live Quick→Standard→Deep 只在用户再次明确授权后运行。

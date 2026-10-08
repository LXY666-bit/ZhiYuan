# Research Workbench invariants

- Research 只实现领域状态和工作流节点，不创建独立 runtime、执行队列、Event bus 或 SSE。
- 所有执行必须使用 canonical `Run(channel="research")`，并保留 ownership、lease、fencing、取消和终结 seam。
- 计划生成与审批在 Run 之前。审批必须在同一事务冻结 Plan/Profile/来源/附件/Prompt/Workflow 快照并预留 Run 与 Manifest。
- Project 只保存 draft/awaiting_approval/frozen；运行状态从最新 Run 投影。
- 业务表是 Evidence、Claim、Section、Artifact、Usage 的权威来源；Checkpoint 的 `thread_id` 是 `run_id`。
- 所有资源查询同时校验 tenant 和 user；管理员不默认越权。
- Writer 只能读取已持久化 Evidence；重要结论使用稳定 `[E#]`。冲突 Evidence 不得仅因分数较低删除。
- 节点写入按 Run/step/section/evidence/artifact 稳定键幂等；业务写与 Event Journal/outbox 同事务。
- 章节并发必须取 Run 冻结 Profile：Quick / Standard / Deep 上限分别为 3 / 5 / 6，实际不超过计划步骤数；单章失败降级而非终止；Critic 只局部修订一次。
- Quick、Standard、Deep 均使用 authenticated Tavily advanced；缺 Key 时显式降级，不得回退无 Key 搜索。秘密不得进入数据库、Snapshot、Event、日志和前端。
- 附件只进入独立 research collection，并按 tenant/project/attachment/version 完整过滤。
- 不默认运行 live 评测。
- Research 搜证复用正式 `backend.rag.utils.retrieve_documents` 的召回/融合/Rerank，不为已经拆分的研究章节重复执行完整 RAG 分类、分解与路由图。只读检索范围由当前执行显式持有，不使用全局“当前快照”。
- 模型调用使用 native async + `ProviderExecutor.acall`，所有重试继承冻结阶段预算与 Run 绝对 deadline，恢复不重新计时。合并审阅同时检查章节问题和核心 Claim；有问题才局部修订，修订后必须复核。Writer 失败时直接披露 insufficient，不核验失败占位文本。

- 冻结 Profile 的决策证据复用开启时，事实章节并行，明确比较/选型标题须等待事实落盘并读取同一 Run 的 Evidence/Claim；等待不能占并发槽。综合写作与发布前核验共用综合阶段 deadline，审阅不通过不能交付确定的整体推荐。

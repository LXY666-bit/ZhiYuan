# ADR-0026：Research Workbench 使用 canonical Run

状态：Accepted  
日期：2026-09-01

## Context

研究工作台包含 Run 前计划审批、长时多阶段执行、可恢复 Checkpoint、Evidence/Claim/Section 业务状态与版本化交付物。知渊已有 canonical Thread / Run / Event / Checkpoint、ownership/lease/fencing 和 Event Journal/outbox。若平移旧版知渊的后台 runtime、事件总线或 SSE，将重新形成双轨实现并破坏取消、恢复与所有权语义。

ADR-0027 统一 Web Research 为受控 authenticated Tavily advanced，并固定经官方 SDK 调用。研究模式仍
须对 Tavily 返回来源与后续网页抓取继承 ADR-0019 的 URL policy、DNS pin、redirect 复验、HTTP budget、
SSRF 防护与秘密隔离。

## Decision

1. ResearchProject 创建专用 `Thread(kind="research")`。计划与审批在 Run 前完成；审批事务冻结 Manifest 并预留 `Run(channel="research")`。
2. `RunAgentExecutor` 对 research channel 做一个局部分支，调用 `ResearchWorkflowRunner`；canonical ownership、lease、fencing、取消、终结、Message、Event Journal 与 SSE 不分叉。
3. 研究业务表是 Evidence、Claim、Section、Artifact、Usage 的权威来源；LangGraph Checkpoint 只负责恢复，`thread_id=run_id`。
4. Planner 使用持久 ResearchPlanJob，冻结 Fast/Grader Model Snapshot，ProviderExecutor 独占网络重试。Planner Usage 不绑定 Run。
5. Artifact 是平台模块，采用服务端生成 storage key、本地原子替换、SHA-256 与所有权下载。Run 内 draft 单例，final 不可变。
6. Quick、Standard 和 Deep 均使用 ADR-0027 的 authenticated Tavily advanced Adapter；它不得回退无 Key 搜索，API Key 不得进入持久化、Snapshot、Event、日志或前端。
7. 研究附件使用独立 collection 和完整 Tenant/Project/Attachment/版本过滤，不发布到全局 Knowledge Base。
8. 研究 deterministic/live 评测保持独立。Live 评测需要再次明确授权。
9. 章节并发是 Run 冻结 Profile 的一部分。Quick / Standard / Deep 分别最多并发 3 / 5 / 6 章，且实际并发不超过计划步骤数；Evidence 与补研预算继续使用 Run-local 锁协调，持久化写入仍受 owner lease 与 fencing 保护。
10. 审批或重新运行时，每个步骤在 Manifest 中冻结为继承 Project 勾选的全部来源；运行时把各来源的候选、保留、过滤和错误计数写入 `ResearchStep.detail_json` 与步骤 Event。知识库搜证复用正式 `retrieve_documents` 的召回、融合、Auto-merging、Rerank 与 Tenant/Document Version 过滤；研究计划已拆分子问题，不再执行完整 RAG 分类、分解与路由图。并发章节在同一次执行中共享只读检索快照，来源调用在线程中传递 deadline 与取消探针。
11. `research-workflow-v4` 在每章写作、核验完成后立即同事务保存 Section、Claim、draft 与 Event；报告按计划顺序组成，恢复时复用已持久化章节。搜证完成不等于步骤完成，`detail_json.phase` 区分 retrieving / writing / verifying / completed，终态仍由 canonical Run executor 拥有。
12. 一次结构化审阅同时完成 Critic 检查与核心 Claim 核验，读取 Evidence 正文；只有发现具体问题时才局部修订一次，修订后再次核验。审阅不可用时返回 insufficient 并公开降级，不能仅凭 Evidence 存在标记 supported。无支持、冲突或未核验 Claim 不建立 supports 关系。确定性引用检查披露缺失或不存在的引用；核心 Claim 保持独立持久身份；审阅同时检查整章重要事实与建议的产品、版本、引用及必要条件，不能把核心 supported 解释为整章全部事实已获验证。
13. Standard/Deep 仅针对观察到的证据缺口追加检索，仍受冻结 Profile 的补研预算约束；综合编辑只消费已持久化章节、Evidence 和核验结果，失败时保留章节并明确披露。中文词项与多对象匹配是有界词法过滤，不替代语义核验。
14. Profile v7 将新 Run 的预算固定为 Quick 90 秒、Standard 180 秒、Deep 300 秒；来源并行数最多等于章节并发上限，慢来源不阻断健康来源。模型使用 native async 调用和 `ProviderExecutor.acall`，单次调用、审阅、补研、综合编辑与重试共享 Run 绝对 deadline。恢复不重置 deadline，章节写作预留综合编辑时间；超时显式降级并保留已持久化结果，不能由局部 timeout 直接写 Run 终态。数据库与文件/PDF 保存时间不承诺受 Provider deadline 硬中断。

15. Profile v7 冻结 Writer 1600 / 2400 / 3200 Token（Quick / Standard / Deep）、审阅 1000、补研 500、综合编辑 1600 的输出上限。仅已识别的阿里云 DeepSeek V4 使用 `extra_body.enable_thinking=false`，其他 Provider 不注入专有参数；达到输出上限显式降级。检索问题去除完整目标中的长背景，显式官方资料要求且具备至多四个拉丁词项时逐对象检索，仍共享来源并发与绝对 deadline，部分搜索失败公开稳定 code 并保留健康结果。网页引用按 URL 与内容哈希复用，内容不同的冲突快照保留；文档路径仅作为排序候选，不代表官方身份已验证，URL 版本线索不代表适用性已核验。

16. Profile v8 保持 v7 时间与输出上限，冻结决策章节复用与综合核验开关。事实章节有界并行；明确的比较/选型标题消费持久事实章节及前序决策的 Evidence/Claim，不占并发槽等待。复用 identity 在持久事务内校验同一 Run，恢复与跨 Run 隔离不变；不新增 Plan wire 字段或第二套事实来源。版本/产品不匹配只作为差异材料，重要新特性保留版本线索；核心 Claim 正确不豁免旁支事实审阅。
17. 综合编辑与发布前核验共享原综合阶段 deadline。核验不通过或不可用时显式 `RESEARCH_SYNTHESIS_UNVERIFIED` 并撤掉该整体推荐，交付已保存的核验结果与章节；不循环重写。保留证据缺口及条件式建议，不以引用数量或 terminal success 承诺准确。

## Consequences

- 研究产品拥有独立 API 和页面，但没有第二套执行或事件通道。
- Project 不复制 Run 终态；展示状态由最新 canonical Run 投影。
- 审批需要 RunRepository 提供 session-aware 原子预留 seam。
- Event payload 必须保持索引式、无敏感正文；UI 收到事件后局部拉取资源。
- 单机受控停机可释放带 Checkpoint 的 research Run 并恢复同一身份；多实例队列仍不在本 ADR 范围。
- 新审批冻结 `research-prompts-v5` / `research-workflow-v5` / Profile v8；既有 Manifest 不被改写，旧冻结任务保留旧预算。Run 指标返回冻结的 Workflow/Profile 版本与时间预算，离线评测指纹同时覆盖 Dataset 与资料内容，评分 v2 拒绝直接比较旧评分基线。

## Rejected alternatives

- 将计划审批建模为 Run 内 HITL：会在冻结输入前创建执行身份，并让 Planner Usage 错绑 Run。
- 新增研究 runtime、SSE 或事件表：违反 ADR-0023。
- 把研究评测塞进 RAG Evaluation Job：两者对象、门禁和成本对比维度不同。
- Standard/Deep 缺 Key时静默 basic 回退：会伪装研究深度并隐藏配置错误。

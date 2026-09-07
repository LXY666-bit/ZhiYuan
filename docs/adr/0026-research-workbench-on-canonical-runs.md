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
10. 审批或重新运行时，每个步骤在 Manifest 中冻结为继承 Project 勾选的全部来源；运行时把各来源的候选、保留、过滤和错误计数写入 `ResearchStep.detail_json` 与步骤 Event。同步 RAG 图在线程中使用无 Queue 的同步 Run Context，不依赖调用线程存在 asyncio event loop。

## Consequences

- 研究产品拥有独立 API 和页面，但没有第二套执行或事件通道。
- Project 不复制 Run 终态；展示状态由最新 canonical Run 投影。
- 审批需要 RunRepository 提供 session-aware 原子预留 seam。
- Event payload 必须保持索引式、无敏感正文；UI 收到事件后局部拉取资源。
- 单机受控停机可释放带 Checkpoint 的 research Run 并恢复同一身份；多实例队列仍不在本 ADR 范围。

## Rejected alternatives

- 将计划审批建模为 Run 内 HITL：会在冻结输入前创建执行身份，并让 Planner Usage 错绑 Run。
- 新增研究 runtime、SSE 或事件表：违反 ADR-0023。
- 把研究评测塞进 RAG Evaluation Job：两者对象、门禁和成本对比维度不同。
- Standard/Deep 缺 Key时静默 basic 回退：会伪装研究深度并隐藏配置错误。

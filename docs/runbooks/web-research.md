# Web Research 运维手册

## 启用前准备

Web Research 默认关闭。搜索使用服务端 `TAVILY_API_KEY` 通过官方 `tavily-python` SDK 调用 Tavily。
SDK 的 endpoint 固定为 Tavily 官方 HTTPS origin，不提供自定义 endpoint 配置，因此 TUN 等透明网络
可以接管该固定出站连接。Tavily 返回的来源 URL、Evidence identity 和后续 `web_fetch` 仍经过 DNS
pinning、SSRF policy、absolute deadline/cancellation 与独立响应大小限制。

管理员可在前端侧栏 **Skill / Tool** 切换 Web Research。`WEB_RESEARCH_ENABLED` 只在数据库
控制面首次创建时作为默认种子；之后以前端保存的配置为准。切换并保存后立即应用，不需要
重启 API 或 worker。

最小配置：

```dotenv
WEB_RESEARCH_ENABLED=true
TAVILY_API_KEY=your_tavily_api_key
```

完整预算见 `.env.example`。上线前重点确认：

- DNS timeout 小于等于 request timeout；DNS 并发和每次地址数量保持最小；这些预算只用于
  `web_fetch`，Tavily SDK 搜索结果不做逐条 DNS 解析；
- default search results 不大于 max results，max results 不大于 max citations；
- title/snippet 不大于单页 content，content 不大于 total evidence；
- 单 Run Web ToolResult 累计不大于 Agent 输入 token 预算的一半；默认为 3 KiB，不要直接恢复
  早期 512 KiB 高值；
- compressed body、解压 response、单页 content 与 total evidence 使用各自独立上限；
- redirect 上限、正文上限和总结果上限不因“抓取失败”被临时放大。

`WEB_RESEARCH_MAX_CONCURRENCY` 同时用于每个 Tool descriptor 和共享 Web Runtime semaphore，
因此 search/fetch 的总在途调用不会越过该值；每个 Run 还受 Agent tool-call、loop 和 deadline
budget 约束。搜索把 request timeout 与 Run 剩余 deadline 的较小值传给 Tavily SDK；网页抓取的
request timeout 则覆盖 DNS 与全部 redirect，均不按 hop 倍增。

网页抓取 HTTP transport 还使用 request-owned watchdog 强制 absolute deadline/cancellation。验收不能只测
完全静默的 socket timeout；必须包含每次在 timeout 前发送一个字节的慢响应头、慢正文和慢 TLS
样例，并确认旁路 socket shutdown 会在总 deadline 附近终止，且请求结束后不会迟到关闭新连接。

Web ToolResult 跨越 ContextBudget Seam 时是原子 JSON 消息。历史旧轮次可以整轮裁掉；
当前轮次若在裁掉可选上下文后仍放不下完整结果，Run 应在模型调用前返回
`POLICY_DENIED` / `web_research` / `context_budget`，trace error code 为
`WEB_TOOL_RESULT_CONTEXT_BUDGET_EXCEEDED`。不得把 `…[truncated by context budget]` 写入
ToolResult JSON。

feature 关闭或未配置 `TAVILY_API_KEY` 时，Registry 不会声明内部的 `WEB_RESEARCH_RUNTIME`
capability；这个符号只表示认证 Runtime 已启用，不是 Secret，也不会作为请求凭据发送。

## 验证

```bash
uv run --frozen python -m backend.tools.registry_cli validate
uv run --frozen python -m backend.tools.registry_cli list-skills --role user
uv run --frozen python -m backend.tools.registry_cli list-tools --role user
uv run --frozen pytest -q tests/test_web_research_contracts.py \
  tests/test_web_url_policy.py tests/test_web_research_http.py \
  tests/test_web_research_runtime.py tests/test_web_tools.py \
  tests/test_agent_runtime.py tests/test_settings_security.py
```

API 启动后还必须执行真实模型与 Tavily API 的端到端冒烟测试；只有 `web_search` 产生
`tool.completed` 且 Run 成功才通过：

```bash
uv run python scripts/smoke_web_research_e2e.py
```

feature 未启用时，`web-research` Skill 与两个 deferred Tool 必须隐藏。启用并保存后，目录可看到
Skill；激活 `/web-research` 后，`tool_search` 才能披露 `web_search` / `web_fetch` schema。
readiness 只应输出 enabled/ready/search-ready 与聚合预算，不得输出 key、query、URL 或正文。

执行烟雾测试：

1. 搜索一个公开、无敏感信息的主题，确认结果包含稳定 evidence/citation identity 和 UTC 时间；
2. 用返回的 `evidence_id` fetch，确认模型不能提交任意 URL；
3. 未知或跨 Run evidence ID 返回 `WEB_EVIDENCE_NOT_AUTHORIZED`；
4. 模型输出 `[标题](webcite:evidence_id)`，服务端只把当前 Run identity 渲染为 Markdown
   link；raw URL、未知/跨 Run identity 和成功取证后无引用均被终态拒绝；
5. ToolAudit 只有 evidence/citation count、output bytes、truncated 和 outcome。

Web Research 为保证终态引用校验，不逐 token 发布模型草稿；Event/SSE 只会在校验通过后收到
一次完整的安全回答。若看到 `WEB_CITATION_*` trace/error，先检查模型是否按 Skill 输出
`webcite:` token，不要关闭终态校验或允许 raw URL。

前端必须保留 DOMPurify allowlist 与 raw HTML renderer 禁用。任何修改 `marked`、`v-html`、
允许 tag/attr 或 URI scheme 的变更，都要重跑 `frontend/src/utils/markdown.spec.ts` 中的 script、
event handler、javascript/data/scheme-relative link 与恶意来源标题攻击用例。

## SSRF 与内容边界验证

在隔离测试环境覆盖下列拒绝样例，不要在生产手工探测内网：loopback、RFC1918、link-local、
特殊用途域名、带 userinfo URL、非 HTTP(S)、非标准或 scheme 混淆端口、DNS 结果混有私网地址、
redirect 转向私网、peer IP 不在 DNS pin、过多 redirect、未知 content type、压缩/解压超限。

确认 `web_fetch` transport 不使用环境 proxy，TLS hostname 验证仍针对 canonical host，且每个
redirect 都重新解析与 pin。Tavily 搜索只通过 SDK 的固定官方 origin 发出，不接受用户或模型提供的
URL；它可以由 TUN 透明转发。Tavily 返回的来源只做确定性 URL canonicalization，只有后续
`web_fetch` 真正访问来源时才进入 DNS pin 与 peer-IP 复核。
DNS timeout、HTTP timeout、Run deadline 或 cancellation 发生时应返回稳定错误码；不得把任意网页
抓取改用普通 hostname client 重试。

## 常见故障

### Skill 或 Tool 不可见

依次检查 feature flag、Runtime capability、调用方是否声明同名 capability、Run 是否
允许 `restricted` network policy、Skill 是否已经激活。
不要把任何伪造 capability 放入 prompt 来“证明已配置”。

### 搜索可用但 fetch 被拒绝

`web_fetch` 只接受当前 Run 中 `web_search` 铸造的 `evidence_id`。重新搜索目标页面，不要把 URL
改写成 identity，也不要扩大为任意 URL fetch。若搜索 provider 没有返回该页面，回答中披露
覆盖缺口。

### DNS、redirect 或内容 policy 拒绝

这通常意味着目标不是安全公网页面、DNS 集合含非 global 地址、redirect 改变了安全边界，或
响应超出类型/字节预算。记录稳定错误码和聚合 outcome；不要记录原 URL/响应，也不要放宽
private/loopback policy。若目标确属内部资源，应设计独立的私网 Tool 和权限，而不是复用本
Skill。

## 禁用、轮换与事件响应

紧急禁用时在前端关闭 Web Research 并保存；控制面尚未初始化时可用
`WEB_RESEARCH_ENABLED=false` 作为首次种子。

审计、Event、checkpoint 或日志中一旦出现 query、URL query string 或正文，应按数据泄露事件
处理并停止发布；不要仅靠日志脱敏规则掩盖错误的数据流。

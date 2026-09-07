# ADR-0027：认证 Tavily Web Research

- 状态：已接受
- 日期：2026-09-05
- 取代：ADR-0019、ADR-0025 中 Tavily Keyless provider 的选择

## 背景

Keyless 搜索依赖代理网络对固定 origin 的特殊处理，出现 DNS Fake-IP 或直连超时时，无法稳定区分
provider 故障与网络路径故障。Research Workbench 还让 Quick 与 Standard/Deep 使用不同搜索身份，
使同一来源选择在不同模式下产生不可比的检索结果。

## 决策

Web Research 只使用官方 `tavily-python` SDK 的固定 Tavily HTTPS endpoint 与服务端
`TAVILY_API_KEY`。Quick、Standard 和 Deep 都使用 authenticated advanced 搜索；删除 Keyless
adapter、手工 Authorization 请求头和自建 Tavily HTTP POST 路径。控制面只保存启用开关，并公开
`api_key_configured` 布尔值；它不接收、不保存或返回 API Key。

feature 已启用但 Key 缺失时，Registry 不披露 `WEB_RESEARCH_RUNTIME` 或 Web Tool；研究步骤记录
明确降级原因，不得发送无 Key 请求或以 basic 搜索代替。API Key 只在 SDK client 实例中存在，且不
进入 Model Snapshot、数据库、Run、Checkpoint、Event、日志或前端。

## 不变量

Tavily 搜索结果只做 URL scheme、authority、userinfo、端口、特殊域名和 IP literal 的确定性校验与
canonicalization，不再对每条搜索结果做 DNS 解析。这样搜索完全沿 Tavily SDK 固定 origin 执行，
不受本机 TUN/Fake-IP DNS 影响。真正访问来源正文的 `web_fetch` 仍使用 Run-local Evidence identity，
并逐跳执行 DNS pin、global-address、peer-IP、redirect、deadline 与 byte budget 校验；搜索结果本身
不构成绕过抓取安全边界的网络权限。

## 结果

部署 Web Research 前必须通过 Secret 管理器注入 `TAVILY_API_KEY`，并重启 API/worker 以读取新环境。
管理员随后在控制面启用能力；缺 Key 时启用请求被拒绝并显示配置状态。

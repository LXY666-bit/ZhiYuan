# Research Workbench Evaluation

这里保存 20 个固定中文研究案例和仓库内资料。离线门禁运行三种模式，共 60 次：

```powershell
uv run python evals/research/run_eval.py --level deterministic --mode all --gated
```

`deterministic` 使用临时 SQLite 数据库和固定 extractive fake model，实际执行正式计划写入、审批、canonical Run、研究工作流、Evidence/Claim/Section/Event 和 Artifact 保存。它只替换检索与模型 Adapter，不根据 Case 标签直接填入成功指标；模型响应可重复，Token 与耗时不代表真实模型成本。SQLite 事务被显式串行化，因此并发锁、lease 和 fencing 的生产协议仍须单独通过 PostgreSQL 集成验证。

评分 v2 的引用覆盖率按正文段落/列表项计算，排除标题、代码、披露提示和来源列表；引用有效性检查编号身份，不能证明语义支持。来源命中率使用实际 Evidence 的资料身份，分别记录 unsupported 与 insufficient，并检查冲突/缺口是否在正文披露。主题覆盖是词项观察指标，真实报告质量仍需要 live 与人工审阅。Dataset fingerprint 同时覆盖案例和资料文件内容；新旧评分版本不能直接比较基线。

Live 会调用真实模型、PostgreSQL 和隔离的 Research Attachment Collection，默认不运行：

```powershell
uv run python evals/research/run_eval.py --level live --mode quick --gated --token <TOKEN>
uv run python evals/research/run_eval.py --level live --mode standard --gated --token <TOKEN>
uv run python evals/research/run_eval.py --level live --mode deep --gated --token <TOKEN>
```

除固定 Dataset 外，`sources/mode_comparison_brief.md` 与
`sources/mode_comparison_conflicts.md` 可用于同题三模式的受控 live 对比。调用 `live_case()` 时传入
`research_sources=["attachments", "web"]`，即可同时验证附件范围、真实 Web Evidence、冲突披露、
报告质量、耗时和 Token；未传该参数时仍保持原有仅附件的门禁行为。
评测源文件以 Markdown 保存便于审阅；live runner 会将其逐字封装为受上传接口支持的 HTML 附件，
不会把不受支持的 `.md` 直接提交给生产接口。

结果写入 `evals/research/results/`（不提交）。成本比较只允许同模式、同 Dataset 指纹的新旧报告：

`research-workflow-v4` 使用 Profile v7 的有界预算、并行来源和合并审阅；离线 Adapter 同时替换检索快照解析、来源召回和原生异步模型调用，保持评测不访问实际数据库目录或 Provider。比较 live 延迟时还需记录 Workflow/Profile 版本并固定模型与硬件；本次离线调用次数减少不能解释为真实服务加速百分比。

```powershell
uv run python evals/research/run_eval.py --level live --mode standard --gated --baseline <OLD_RESULT.json> --token <TOKEN>
```

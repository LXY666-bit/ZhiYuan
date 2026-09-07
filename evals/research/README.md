# Research Workbench Evaluation

这里保存 20 个固定中文研究案例和仓库内资料。离线门禁运行三种模式，共 60 次：

```powershell
uv run python evals/research/run_eval.py --level deterministic --mode all --gated
```

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

```powershell
uv run python evals/research/run_eval.py --level live --mode standard --gated --baseline <OLD_RESULT.json> --token <TOKEN>
```

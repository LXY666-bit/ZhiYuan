# Research Evaluation AGENTS.md

本目录是独立的研究工作台质量门禁，不并入 `evals/rag/` 的 RAG Evaluation Job。

- `deterministic` 必须离线、固定、可重复，三种模式分别运行全部 20 个 Case。
- `live` 只调用正式 Research API、canonical Run 和隔离附件索引，不复制生产工作流。
- Live 必须显式提供 Token；按 Quick → Standard → Deep 分层运行，前一层失败即停止。
- 输出不得保存凭据、附件正文、内部路径、完整 Provider 响应或异常详情。
- 同模式新旧报告才可比较资源回归；不得用 Quick 与 Standard/Deep 的 Token 差异判断回归。


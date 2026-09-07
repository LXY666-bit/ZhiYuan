# 技术能力目录

LangGraph 适合显式状态图、条件路由和可恢复工作流。CrewAI 更强调角色协作抽象。SSE 是服务端到浏览器的单向事件流，原生支持事件 ID 和重连；WebSocket 支持双向通信但运维复杂度更高。

Milvus 面向独立向量检索服务和混合检索，pgvector 适合希望复用 PostgreSQL 事务与运维体系的中小规模场景。具体阈值必须通过业务数据评测确定。

部分模型会在 usage metadata 中返回缓存命中 Token，但未知私有模型的字段支持情况没有证据。


<script setup lang="ts">
import type { RagTrace } from '@/types/chat';

defineProps<{
  ragTrace: RagTrace;
}>();

function stageLabel(trace: RagTrace): string {
  if (trace.retrieval_stage === 'synthesis') return '并行合成';
  if (trace.retrieval_stage === 'expanded') return '已扩展';
  return '初次检索';
}
</script>

<template>
  <div class="rag-trace">
    <details class="trace-toggle">
      <summary>
        <i class="ph ph-magnifying-glass"></i>
        <span>检索过程</span>
        <span class="trace-badge">{{ stageLabel(ragTrace) }}</span>
      </summary>
      <div class="trace-body">
        <!-- Complexity banner -->
        <div v-if="ragTrace.complexity" :class="['trace-complexity', ragTrace.complexity === 'complex' ? 'complexity-complex' : 'complexity-simple']">
          <i :class="ragTrace.complexity === 'complex' ? 'ph ph-share-network' : 'ph ph-arrow-right'"></i>
          <span>{{ ragTrace.complexity === 'complex' ? '复杂问题 · 并行检索' : '简单问题 · 标准检索' }}</span>
          <span v-if="ragTrace.complexity_reason" class="complexity-reason">{{ ragTrace.complexity_reason }}</span>
        </div>

        <!-- Sub-questions -->
        <div v-if="ragTrace.sub_questions && ragTrace.sub_questions.length" class="trace-sub-questions">
          <h4>子问题分解（{{ ragTrace.sub_agent_count || ragTrace.sub_questions.length }} 路并行）</h4>
          <ol>
            <li v-for="(sq, sqIdx) in ragTrace.sub_questions" :key="sqIdx">{{ sq }}</li>
          </ol>
        </div>

        <!-- Trace grid -->
        <div class="trace-grid">
          <div class="trace-item" v-if="ragTrace.tool_used">
            <span class="trace-key">工具</span>
            <span class="trace-val">{{ ragTrace.tool_name }}</span>
          </div>
          <div class="trace-item" v-if="ragTrace.retrieval_pipeline">
            <span class="trace-key">流水线</span>
            <span class="trace-val">召回 → 合并 → 重排 → 过滤</span>
          </div>
          <div class="trace-item" v-if="ragTrace.retrieval_mode">
            <span class="trace-key">检索模式</span>
            <span class="trace-val">{{ ragTrace.retrieval_mode === 'hybrid' ? '混合检索' : ragTrace.retrieval_mode === 'dense_fallback' ? '稠密降级' : ragTrace.retrieval_mode }}</span>
          </div>
          <div class="trace-item" v-if="ragTrace.grade_score">
            <span class="trace-key">相关性</span>
            <span class="trace-val" :class="ragTrace.grade_score === 'yes' ? 'text-success' : 'text-warn'">{{ ragTrace.grade_score === 'yes' ? '相关' : '不相关' }}</span>
          </div>
          <div class="trace-item" v-if="ragTrace.grade_skipped">
            <span class="trace-key">评分跳过</span>
            <span class="trace-val text-warn">检索为空，直接重写</span>
          </div>
          <div class="trace-item" v-if="ragTrace.rewrite_strategy">
            <span class="trace-key">重写策略</span>
            <span class="trace-val">{{ ragTrace.rewrite_strategy }}</span>
          </div>
          <div class="trace-item" v-if="ragTrace.candidate_k">
            <span class="trace-key">候选池</span>
            <span class="trace-val">{{ ragTrace.candidate_k }}（来源: {{ ragTrace.candidate_k_source === 'env' ? '显式配置' : '倍数计算' }}）</span>
          </div>
          <div class="trace-item" v-if="ragTrace.post_merge_candidate_count !== null && ragTrace.post_merge_candidate_count !== undefined">
            <span class="trace-key">合并后候选</span>
            <span class="trace-val">{{ ragTrace.post_merge_candidate_count }}</span>
          </div>
          <div class="trace-item" v-if="ragTrace.rerank_enabled !== null && ragTrace.rerank_enabled !== undefined">
            <span class="trace-key">重排序</span>
            <span class="trace-val">{{ ragTrace.rerank_applied ? '已执行 → ' + ragTrace.post_rerank_count + ' 条' : '跳过' }}</span>
          </div>
          <div class="trace-item" v-if="ragTrace.rerank_min_score && ragTrace.rerank_min_score > 0">
            <span class="trace-key">最低阈值</span>
            <span class="trace-val">{{ ragTrace.rerank_min_score }}（过滤后 {{ ragTrace.post_threshold_count }} 条）</span>
          </div>
          <div class="trace-item" v-if="ragTrace.auto_merge_enabled !== null && ragTrace.auto_merge_enabled !== undefined">
            <span class="trace-key">自动合并</span>
            <span class="trace-val">{{ ragTrace.auto_merge_applied ? '已合并（' + ragTrace.auto_merge_replaced_chunks + ' 段）' : '未触发' }}</span>
          </div>
          <div class="trace-item" v-if="ragTrace.recall_count !== null && ragTrace.recall_count !== undefined">
            <span class="trace-key">漏斗</span>
            <span class="trace-val">{{ ragTrace.recall_count }} → 合并 → {{ ragTrace.post_merge_candidate_count || ragTrace.candidate_count || '?' }} → 重排 → {{ ragTrace.post_rerank_count || '?' }} → 阈值 → {{ ragTrace.post_threshold_count || '?' }}</span>
          </div>
          <div class="trace-item" v-if="ragTrace.retrieval_empty">
            <span class="trace-key">结果</span>
            <span class="trace-val text-warn">检索为空</span>
          </div>
          <div class="trace-item" v-if="ragTrace.synthesis_merged_count">
            <span class="trace-key">合成合并</span>
            <span class="trace-val">{{ ragTrace.synthesis_merged_count }} 条 → 去重后 {{ ragTrace.retrieved_chunks ? ragTrace.retrieved_chunks.length : '?' }} 条</span>
          </div>
          <div class="trace-item" v-if="ragTrace.step_back_question">
            <span class="trace-key">退步问题</span>
            <span class="trace-val pre">{{ ragTrace.step_back_question }}</span>
          </div>
          <div class="trace-item" v-if="ragTrace.hypothetical_doc">
            <span class="trace-key">HyDE 文档</span>
            <span class="trace-val pre">{{ ragTrace.hypothetical_doc.substring(0, 200) }}{{ ragTrace.hypothetical_doc.length > 200 ? '...' : '' }}</span>
          </div>
        </div>

        <!-- Sub-agent traces -->
        <div v-if="ragTrace.sub_traces && ragTrace.sub_traces.length" class="trace-sub-traces">
          <h4>子Agent检索详情</h4>
          <div v-for="(st, stIdx) in ragTrace.sub_traces" :key="stIdx" class="sub-trace-card">
            <div class="sub-trace-header">
              <span class="sub-trace-label">子问题 {{ stIdx + 1 }}</span>
              <span class="sub-trace-query">{{ (st.query || '').substring(0, 60) }}{{ (st.query || '').length > 60 ? '…' : '' }}</span>
            </div>
            <div class="sub-trace-stats" v-if="st.retrieved_chunks">
              <span>{{ st.retrieved_chunks.length }} 个片段</span>
              <span v-if="st.retrieval_mode">模式: {{ st.retrieval_mode }}</span>
              <span v-if="st.rewrite_strategy">策略: {{ st.rewrite_strategy }}</span>
            </div>
          </div>
        </div>

        <!-- Retrieved chunks -->
        <div v-if="ragTrace.retrieved_chunks && ragTrace.retrieved_chunks.length" class="trace-chunks">
          <h4>检索到的文本片段</h4>
          <div v-for="(chunk, cIdx) in ragTrace.retrieved_chunks" :key="cIdx" class="trace-chunk">
            <div class="chunk-header">
              <span class="chunk-source">{{ chunk.filename }}</span>
              <span class="chunk-page">第 {{ chunk.page_number || '?' }} 页</span>
              <span v-if="chunk.rerank_score !== null && chunk.rerank_score !== undefined" class="chunk-score">相关性 {{ Number(chunk.rerank_score).toFixed(4) }}</span>
            </div>
            <p class="chunk-text">{{ chunk.text }}</p>
          </div>
        </div>
      </div>
    </details>
  </div>
</template>

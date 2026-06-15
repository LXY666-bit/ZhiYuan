<script setup lang="ts">
import type { RetrievedChunk } from '@/types/chat';

defineProps<{
  chunks: RetrievedChunk[];
}>();
</script>

<template>
  <div v-if="chunks && chunks.length" class="rag-trace">
    <details class="trace-toggle">
      <summary>
        <i class="ph ph-magnifying-glass"></i>
        <span>检索到的文本片段</span>
        <span class="trace-badge">{{ chunks.length }} 条</span>
      </summary>
      <div class="trace-body">
        <div class="trace-chunks">
          <div v-for="(chunk, cIdx) in chunks" :key="cIdx" class="trace-chunk">
            <div class="chunk-header">
              <span class="chunk-source">{{ chunk.filename }}</span>
              <span class="chunk-page">第 {{ chunk.page_number || '?' }} 页</span>
              <span v-if="chunk.rerank_score !== null && chunk.rerank_score !== undefined" class="chunk-score">
                相关性 {{ Number(chunk.rerank_score).toFixed(4) }}
              </span>
            </div>
            <p class="chunk-text">{{ chunk.text }}</p>
          </div>
        </div>
      </div>
    </details>
  </div>
</template>

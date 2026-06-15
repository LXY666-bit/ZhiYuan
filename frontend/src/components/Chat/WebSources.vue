<script setup lang="ts">
import type { WebSources } from '@/types/chat';

defineProps<{
  webSources: WebSources;
}>();
</script>

<template>
  <div v-if="webSources && webSources.sources" class="web-sources">
    <details class="trace-toggle" open>
      <summary>
        <i class="ph ph-globe"></i>
        <span>搜索来源</span>
        <span class="trace-badge">{{ webSources.sources.length }} 条结果</span>
      </summary>
      <div class="trace-body">
        <div v-for="(src, idx) in webSources.sources" :key="idx" class="web-source-item">
          <a :href="src.url" target="_blank" class="web-source-title">{{ src.title }}</a>
          <p class="web-source-snippet">{{ src.content }}</p>
        </div>
      </div>
    </details>
  </div>
</template>

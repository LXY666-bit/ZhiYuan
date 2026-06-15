<script setup lang="ts">
import type { RagStep, GroupedRagSteps } from '@/types/chat';

const props = defineProps<{
  ragSteps: RagStep[];
  groupedSteps: GroupedRagSteps | null;
}>();

function lastLabel(): string {
  if (!props.ragSteps || !props.ragSteps.length) return '正在分析问题...';
  return props.ragSteps[props.ragSteps.length - 1].label || '正在分析问题...';
}
</script>

<template>
  <div class="msg-bubble thinking-bubble">
    <div class="thinking-indicator">
      <span class="think-dot"></span>
      <span class="think-dot"></span>
      <span class="think-dot"></span>
      <span class="think-label">{{ lastLabel() }}</span>
    </div>
    <div v-if="ragSteps && ragSteps.length" class="rag-live-steps">
      <template v-for="(group, gKey) in (groupedSteps || {})" :key="gKey">
        <div v-if="gKey !== '__ungrouped__' && group.length" class="rag-step-group-label">
          <i class="ph ph-share-network"></i> 子问题：{{ String(gKey).length > 40 ? String(gKey).substring(0, 40) + '…' : gKey }}
        </div>
        <div v-for="(step, sIdx) in group" :key="gKey + '-' + sIdx" class="rag-live-step">
          <span class="rag-step-icon">{{ step.icon }}</span>
          <span class="rag-step-label">{{ step.label }}</span>
          <span v-if="step.detail" class="rag-step-detail">{{ step.detail }}</span>
        </div>
      </template>
    </div>
  </div>
</template>

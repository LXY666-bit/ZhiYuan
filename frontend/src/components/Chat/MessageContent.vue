<script setup lang="ts">
import { parseMarkdown, escapeHtml } from '@/utils/markdown';

const props = defineProps<{
  text: string;
  isUser: boolean;
  msgIndex: number;
}>();

const emit = defineEmits<{
  citeClick: [msgIndex: number, chunkIndex: number];
}>();
</script>

<template>
  <div
    v-if="props.isUser"
    class="msg-bubble"
    v-html="escapeHtml(props.text)"
  />
  <div
    v-else
    class="msg-bubble"
    v-html="parseMarkdown(props.text)"
  />
</template>

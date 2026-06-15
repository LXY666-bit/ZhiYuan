<script setup lang="ts">
import type { Message } from '@/types/chat';
import MessageContent from './MessageContent.vue';
import ThinkingTrace from './ThinkingTrace.vue';
import References from './References.vue';
import RetrievalTraceDetails from './RetrievalTraceDetails.vue';
import WebSources from './WebSources.vue';

defineProps<{
  msg: Message;
  index: number;
}>();
</script>

<template>
  <div :class="['message', msg.isUser ? 'msg-user' : 'msg-bot']">
    <!-- Thinking state -->
    <template v-if="!msg.isUser && msg.isThinking && !msg.text">
      <ThinkingTrace
        :rag-steps="msg.ragSteps || []"
        :grouped-steps="msg._groupedSteps || null"
      />
    </template>
    <!-- Normal message -->
    <template v-else>
      <MessageContent
        :text="msg.text"
        :is-user="msg.isUser"
        :msg-index="index"
      />
    </template>
    <!-- RAG Trace -->
    <RetrievalTraceDetails
      v-if="!msg.isUser && msg.ragTrace"
      :rag-trace="msg.ragTrace"
    />
    <!-- Web Sources -->
    <WebSources
      v-if="!msg.isUser && msg.webSources"
      :web-sources="msg.webSources"
    />
    <!-- References (chunks only, for bots without full trace) -->
    <References
      v-if="!msg.isUser && msg.ragTrace?.retrieved_chunks && !msg.ragTrace.tool_used"
      :chunks="msg.ragTrace.retrieved_chunks"
    />
  </div>
</template>

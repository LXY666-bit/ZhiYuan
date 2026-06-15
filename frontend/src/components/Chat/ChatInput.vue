<script setup lang="ts">
import { useChatStore } from '@/stores/chat';

const chatStore = useChatStore();

function handleKeyDown(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey && !chatStore.isComposing) {
    event.preventDefault();
    chatStore.handleSend();
  }
}

function autoResize(event: Event) {
  const ta = event.target as HTMLTextAreaElement;
  ta.style.height = 'auto';
  ta.style.height = ta.scrollHeight + 'px';
}
</script>

<template>
  <div class="input-bar">
    <div :class="['input-wrapper', { focused: chatStore.inputFocused }]">
      <textarea
        v-model="chatStore.userInput"
        placeholder="输入消息，Enter 发送，Shift+Enter 换行"
        @keydown="handleKeyDown"
        @input="autoResize"
        @focus="chatStore.inputFocused = true"
        @blur="chatStore.inputFocused = false"
        @compositionstart="chatStore.isComposing = true"
        @compositionend="chatStore.isComposing = false"
        :disabled="chatStore.isLoading"
        rows="1"
      ></textarea>
      <button
        v-if="!chatStore.isLoading"
        @click="chatStore.handleSend()"
        :disabled="!chatStore.userInput.trim()"
        :class="['btn-send', { ready: chatStore.userInput.trim() }]"
        title="发送"
      >
        <i class="ph ph-arrow-up"></i>
      </button>
      <button
        v-else
        @click="chatStore.handleStop()"
        class="btn-stop"
        title="停止"
      >
        <i class="ph ph-stop-circle"></i>
      </button>
    </div>
    <p class="input-disclaimer">AI 生成内容可能存在错误，请仔细核查</p>
  </div>
</template>

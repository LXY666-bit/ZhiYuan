<script setup lang="ts">
import { ref } from 'vue';
import { useChatStore } from '@/stores/chat';
import WelcomeScreen from './WelcomeScreen.vue';
import MessageItem from './MessageItem.vue';
import ChatInput from './ChatInput.vue';

const chatStore = useChatStore();
const chatContainer = ref<HTMLElement | null>(null);

// Expose container ref to store for scrolling
chatStore.chatContainerRef = chatContainer as unknown as HTMLElement | null;
</script>

<template>
  <div class="chat-stage">
    <div class="chat-header-bar">
      <div class="chat-status">
        <span class="status-dot"></span>
        <span>知渊在线中</span>
      </div>
      <button @click="chatStore.handleClearChat()" class="btn-icon" title="清空对话">
        <i class="ph ph-broom"></i>
      </button>
    </div>

    <div ref="chatContainer" class="chat-scroll">
      <WelcomeScreen v-if="!chatStore.messages.length" />

      <MessageItem
        v-for="(msg, index) in chatStore.messages"
        :key="index"
        :msg="msg"
        :index="index"
      />
    </div>

    <ChatInput />
  </div>
</template>

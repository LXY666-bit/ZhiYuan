<script setup lang="ts">
import { useChatStore } from '@/stores/chat';

const chatStore = useChatStore();

const welcomeHints = [
  '知渊是什么？',
  '介绍一下 RAG 检索流程',
  '有哪些技术规格？',
  '支持哪些文档格式？',
];
</script>

<template>
  <div class="welcome-state">
    <div class="brand-mark-lg">
      <svg viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path d="M24 6 L38 20 L38 38 L28 38 L28 26 L20 26 L20 38 L10 38 L10 20 Z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/>
        <circle cx="24" cy="18" r="5" stroke="currentColor" stroke-width="1.5"/>
        <circle cx="22" cy="17" r="1.5" fill="currentColor"/>
        <circle cx="27" cy="17" r="1.5" fill="currentColor"/>
        <path d="M23 21 Q23 24 20 24" stroke="currentColor" stroke-width="0.8" stroke-linecap="round"/>
        <path d="M25 21 Q25 24 28 24" stroke="currentColor" stroke-width="0.8" stroke-linecap="round"/>
      </svg>
    </div>
    <h2>你好，我是 知渊</h2>
    <p>基于 Agentic RAG 的智能助手，可以回答关于你上传文档的任何问题</p>
    <div class="welcome-hints">
      <button
        v-for="hint in welcomeHints"
        :key="hint"
        @click="chatStore.userInput = hint; chatStore.handleSend()"
        class="hint-chip"
      >{{ hint }}</button>
    </div>
  </div>
</template>

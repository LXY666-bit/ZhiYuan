<script setup lang="ts">
import { useSessionStore } from '@/stores/sessions';
import { useChatStore } from '@/stores/chat';

const sessionStore = useSessionStore();
const chatStore = useChatStore();
</script>

<template>
  <div v-if="sessionStore.showHistorySidebar" class="history-overlay" @click.self="sessionStore.showHistorySidebar = false">
    <div class="history-panel">
      <div class="history-panel-header">
        <h3>历史记录</h3>
        <button @click="sessionStore.showHistorySidebar = false" class="btn-icon">
          <i class="ph ph-x"></i>
        </button>
      </div>
      <div v-if="!sessionStore.sessions.length" class="empty-state">
        <i class="ph ph-chat-dots"></i>
        <p>暂无历史记录</p>
      </div>
      <div v-else class="history-list">
        <div
          v-for="s in sessionStore.sessions"
          :key="s.session_id"
          :class="['history-item', { active: s.session_id === chatStore.sessionId }]"
          @click="chatStore.loadSession(s.session_id)"
        >
          <div class="history-item-body">
            <span class="history-title">{{ s.title || '未命名对话' }}</span>
            <span class="history-meta">{{ s.message_count || 0 }} 条消息 · {{ new Date(s.updated_at).toLocaleDateString('zh-CN') }}</span>
          </div>
          <button
            @click.stop="sessionStore.deleteSession(s.session_id)"
            class="btn-icon btn-sm"
            title="删除"
          >
            <i class="ph ph-trash"></i>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

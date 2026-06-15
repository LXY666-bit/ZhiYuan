<script setup lang="ts">
import { useAuthStore } from '@/stores/auth';
import { useChatStore } from '@/stores/chat';
import { useSessionStore } from '@/stores/sessions';

const authStore = useAuthStore();
const chatStore = useChatStore();
const sessionStore = useSessionStore();

async function handleHistory() {
  chatStore.activeNav = 'history';
  sessionStore.showHistorySidebar = true;
  await sessionStore.fetchSessions();
}

function handleSettings() {
  if (!authStore.isAdmin) { alert('仅管理员可访问知识库管理'); return; }
  chatStore.activeNav = 'settings';
  sessionStore.showHistorySidebar = false;
}

function handleUserManagement() {
  if (!authStore.isAdmin) { alert('仅管理员可访问用户管理'); return; }
  chatStore.activeNav = 'users';
  sessionStore.showHistorySidebar = false;
}
</script>

<template>
  <aside class="sidebar">
    <div class="sidebar-brand">
      <div class="brand-mark">
        <svg viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M24 6 L38 20 L38 38 L28 38 L28 26 L20 26 L20 38 L10 38 L10 20 Z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/>
          <circle cx="24" cy="18" r="5" stroke="currentColor" stroke-width="1.5"/>
          <circle cx="22" cy="17" r="1.5" fill="currentColor"/>
          <circle cx="27" cy="17" r="1.5" fill="currentColor"/>
          <path d="M23 21 Q23 24 20 24" stroke="currentColor" stroke-width="0.8" stroke-linecap="round"/>
          <path d="M25 21 Q25 24 28 24" stroke="currentColor" stroke-width="0.8" stroke-linecap="round"/>
        </svg>
      </div>
      <div class="brand-text">
        <span class="brand-name">知渊</span>
        <span class="brand-tagline">智能知识库助手</span>
      </div>
    </div>

    <nav class="sidebar-nav">
      <button @click="chatStore.handleNewChat()" :class="['nav-item', { active: chatStore.activeNav === 'newChat' }]">
        <i class="ph ph-chat-circle"></i>
        <span>新对话</span>
      </button>
      <button @click="handleHistory" :class="['nav-item', { active: chatStore.activeNav === 'history' }]">
        <i class="ph ph-clock-counter-clockwise"></i>
        <span>历史记录</span>
      </button>
      <button v-if="authStore.isAdmin" @click="handleSettings" :class="['nav-item', { active: chatStore.activeNav === 'settings' }]">
        <i class="ph ph-database"></i>
        <span>知识库管理</span>
      </button>
      <button v-if="authStore.isAdmin" @click="handleUserManagement" :class="['nav-item', { active: chatStore.activeNav === 'users' }]">
        <i class="ph ph-users"></i>
        <span>用户管理</span>
      </button>
    </nav>

    <div class="sidebar-footer">
      <div v-if="authStore.isAuthenticated" class="user-card">
        <div class="user-avatar">{{ authStore.currentUser?.username?.charAt(0).toUpperCase() }}</div>
        <div class="user-info">
          <span class="user-name">{{ authStore.currentUser?.username }}</span>
          <span class="user-role">{{ authStore.isAdmin ? '管理员' : '普通用户' }}</span>
        </div>
      </div>
      <button v-if="authStore.isAuthenticated" @click="authStore.handleLogout(); chatStore.handleNewChat();" class="nav-item logout-btn">
        <i class="ph ph-sign-out"></i>
        <span>退出登录</span>
      </button>
    </div>
  </aside>
</template>

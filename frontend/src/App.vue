<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue';
import { useAuthStore } from '@/stores/auth';
import { useChatStore } from '@/stores/chat';
import Sidebar from './components/Sidebar.vue';
import AuthPanel from './components/AuthPanel.vue';
import ChatArea from './components/Chat/ChatArea.vue';
import DocumentSettings from './components/Documents/DocumentSettings.vue';
import UserManagement from './components/Users/UserManagement.vue';
import HistorySidebar from './components/HistorySidebar.vue';

const authStore = useAuthStore();
const chatStore = useChatStore();

function handleUnauthorized() {
  authStore.handleLogout();
  chatStore.handleNewChat();
}

onMounted(() => {
  if (authStore.token) {
    authStore.fetchMe().catch(() => {});
  }
  window.addEventListener('unauthorized', handleUnauthorized);
});

onUnmounted(() => {
  window.removeEventListener('unauthorized', handleUnauthorized);
});
</script>

<template>
  <!-- Background geometric shapes -->
  <div class="bg-geo">
    <div class="geo-shape circle"></div>
    <div class="geo-shape triangle"></div>
    <div class="geo-shape square"></div>
    <div class="geo-shape hexagon"></div>
    <div class="geo-shape circle"></div>
    <div class="geo-shape square"></div>
  </div>

  <div class="app-shell">
    <Sidebar v-if="authStore.isAuthenticated" />

    <main class="main-stage">
      <!-- Auth -->
      <AuthPanel v-if="!authStore.isAuthenticated" />

      <!-- Main content -->
      <template v-else>
        <DocumentSettings v-if="chatStore.activeNav === 'settings'" />
        <UserManagement v-else-if="chatStore.activeNav === 'users'" />
        <ChatArea v-else />

        <HistorySidebar />
      </template>
    </main>
  </div>
</template>

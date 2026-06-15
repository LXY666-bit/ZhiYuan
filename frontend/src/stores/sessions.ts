import { defineStore } from 'pinia';
import { ref } from 'vue';
import type { ChatSession } from '@/types/chat';
import api from '@/utils/api';

export const useSessionStore = defineStore('sessions', () => {
  const sessions = ref<ChatSession[]>([]);
  const showHistorySidebar = ref(false);

  async function fetchSessions() {
    try {
      const response = await api.get<{ sessions: ChatSession[] }>('/sessions');
      sessions.value = response.data.sessions;
    } catch {
      // silently fail
    }
  }

  async function deleteSession(sessionId: string) {
    try {
      await api.delete(`/sessions/${encodeURIComponent(sessionId)}`);
      sessions.value = sessions.value.filter(s => s.session_id !== sessionId);
    } catch (error: unknown) {
      const msg = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '删除失败';
      alert('删除会话失败：' + msg);
    }
  }

  return { sessions, showHistorySidebar, fetchSessions, deleteSession };
});

import { defineStore } from 'pinia';
import { ref, nextTick, watch } from 'vue';
import type { Message, RagStep, GroupedRagSteps, SSEEvent, ChatSession } from '@/types/chat';
import { useAuthStore } from './auth';
import { useSessionStore } from './sessions';

export const useChatStore = defineStore('chat', () => {
  const messages = ref<Message[]>([]);
  const userInput = ref('');
  const isLoading = ref(false);
  const inputFocused = ref(false);
  const isComposing = ref(false);
  const activeNav = ref<'newChat' | 'history' | 'settings' | 'users'>('newChat');
  const sessionId = ref('session_' + Date.now());
  const abortController = ref<AbortController | null>(null);
  const chatContainerRef = ref<HTMLElement | null>(null);

  // ── RAG Step Grouping ──
  function groupRagSteps(steps: RagStep[]): GroupedRagSteps {
    const groups: GroupedRagSteps = {};
    let ungrouped: RagStep[] = [];
    let hasGroup = false;
    for (const step of steps) {
      if (step.group) {
        hasGroup = true;
        if (!groups[step.group]) groups[step.group] = [];
        groups[step.group].push(step);
      } else {
        ungrouped.push(step);
      }
    }
    if (!hasGroup) return { __ungrouped__: ungrouped };
    groups.__ungrouped__ = ungrouped;
    return groups;
  }

  function traceStageLabel(trace: { retrieval_stage?: string }): string {
    if (!trace) return '';
    if (trace.retrieval_stage === 'synthesis') return '并行合成';
    if (trace.retrieval_stage === 'expanded') return '已扩展';
    return '初次检索';
  }

  // ── Scroll ──
  function scrollToBottom() {
    if (chatContainerRef.value) {
      chatContainerRef.value.scrollTop = chatContainerRef.value.scrollHeight;
    }
  }

  // ── Actions ──
  function handleNewChat() {
    messages.value = [];
    sessionId.value = 'session_' + Date.now();
    activeNav.value = 'newChat';
    const sessionStore = useSessionStore();
    sessionStore.showHistorySidebar = false;
  }

  function handleClearChat() {
    if (confirm('确定要清空当前对话吗？')) {
      messages.value = [];
    }
  }

  function handleStop() {
    if (abortController.value) {
      abortController.value.abort();
    }
  }

  async function loadSession(sid: string) {
    sessionId.value = sid;
    const sessionStore = useSessionStore();
    sessionStore.showHistorySidebar = false;
    activeNav.value = 'newChat';
    try {
      const authStore = useAuthStore();
      const token = authStore.token;
      const response = await fetch(`/sessions/${encodeURIComponent(sid)}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!response.ok) throw new Error('加载失败');
      const data = await response.json();
      messages.value = data.messages.map((msg: { type: string; content: string; rag_trace?: unknown; web_sources?: unknown }) => ({
        text: msg.content,
        isUser: msg.type === 'human',
        ragTrace: msg.rag_trace || null,
        webSources: msg.web_sources || null,
      }));
      await nextTick();
      scrollToBottom();
    } catch {
      alert('加载会话失败');
      messages.value = [];
    }
  }

  async function handleSend() {
    const authStore = useAuthStore();
    if (!authStore.isAuthenticated) { alert('请先登录'); return; }
    const text = userInput.value.trim();
    if (!text || isLoading.value || isComposing.value) return;

    messages.value.push({ text, isUser: true });
    userInput.value = '';
    await nextTick();
    scrollToBottom();

    isLoading.value = true;
    messages.value.push({
      text: '', isUser: false, isThinking: true,
      ragTrace: null, ragSteps: [], webSources: null,
    });
    const botMsgIdx = messages.value.length - 1;
    abortController.value = new AbortController();

    try {
      const response = await fetch('/chat/stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${authStore.token}`,
        },
        body: JSON.stringify({ message: text, session_id: sessionId.value }),
        signal: abortController.value.signal,
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);

      const reader = response.body!.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        let eventEndIdx: number;
        while ((eventEndIdx = buffer.indexOf('\n\n')) !== -1) {
          const eventStr = buffer.slice(0, eventEndIdx);
          buffer = buffer.slice(eventEndIdx + 2);
          if (!eventStr.startsWith('data: ')) continue;

          const dataStr = eventStr.slice(6);
          if (dataStr === '[DONE]') continue;
          try {
            const data = JSON.parse(dataStr) as SSEEvent;
            const bot = messages.value[botMsgIdx];
            if (data.type === 'content') {
              if (bot.isThinking) bot.isThinking = false;
              bot.text += data.content;
            } else if (data.type === 'trace') {
              bot.ragTrace = data.rag_trace;
            } else if (data.type === 'web_sources') {
              bot.webSources = data.web_sources;
            } else if (data.type === 'rag_step') {
              if (!bot.ragSteps) bot.ragSteps = [];
              bot.ragSteps.push(data.step);
              bot._groupedSteps = groupRagSteps(bot.ragSteps);
            } else if (data.type === 'session_title') {
              const sessionStore = useSessionStore();
              const session = sessionStore.sessions.find(s => s.session_id === sessionId.value);
              if (session) {
                session.title = data.title;
                session.message_count = 1;
              }
            } else if (data.type === 'error') {
              bot.isThinking = false;
              bot.text += `\n\n*错误：${data.content}*`;
            }
          } catch { /* parse error, skip */ }
        }
        await nextTick();
        scrollToBottom();
      }
    } catch (error: unknown) {
      const bot = messages.value[botMsgIdx];
      if (error instanceof DOMException && error.name === 'AbortError') {
        bot.isThinking = false;
        bot.text = bot.text ? bot.text + '\n\n*— 已停止 —*' : '*(已停止回答)*';
      } else {
        bot.isThinking = false;
        bot.text = `发生错误：${(error as Error).message}`;
      }
    } finally {
      isLoading.value = false;
      abortController.value = null;
      await nextTick();
      scrollToBottom();
    }
  }

  return {
    messages, userInput, isLoading, inputFocused, isComposing,
    activeNav, sessionId, abortController, chatContainerRef,
    groupRagSteps, traceStageLabel, scrollToBottom,
    handleNewChat, handleClearChat, handleStop, loadSession, handleSend,
  };
});

import { defineStore } from 'pinia';
import { ref, computed } from 'vue';
import type { CurrentUser, AuthForm } from '@/types/user';
import api from '@/utils/api';

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string>(localStorage.getItem('accessToken') || '');
  const currentUser = ref<CurrentUser | null>(null);
  const authMode = ref<'login' | 'register'>('login');
  const authForm = ref<AuthForm>({ username: '', password: '', role: 'user', admin_code: '', remember_me: false });
  const authLoading = ref(false);
  const authError = ref<string>('');

  const isAuthenticated = computed(() => !!token.value && !!currentUser.value);
  const isAdmin = computed(() => currentUser.value?.role === 'admin');

  async function fetchMe() {
    try {
      const response = await api.get<CurrentUser>('/auth/me');
      currentUser.value = response.data;
    } catch {
      handleLogout();
      throw new Error('认证失败');
    }
  }

  async function handleAuthSubmit() {
    if (authLoading.value) return;
    const username = authForm.value.username.trim();
    const password = authForm.value.password.trim();
    if (!username || !password) {
      authError.value = '用户名和密码不能为空';
      return;
    }

    authError.value = '';
    authLoading.value = true;
    try {
      const endpoint = authMode.value === 'login' ? '/auth/login' : '/auth/register';
      const payload: Record<string, string | null> = { username, password };
      if (authMode.value === 'register') {
        payload.role = authForm.value.role;
        payload.admin_code = authForm.value.admin_code || null;
      }

      const response = await api.post<{ access_token: string; username: string; role: string }>(endpoint, payload);
      const data = response.data;

      token.value = data.access_token;
      currentUser.value = { username: data.username, role: data.role as 'user' | 'admin' };
      localStorage.setItem('accessToken', token.value);
      if (authForm.value.remember_me) {
        localStorage.setItem('rememberMe', 'true');
      }
      authForm.value.password = '';
      authForm.value.admin_code = '';
    } catch (error: unknown) {
      const msg = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '认证失败';
      authError.value = msg;
    } finally {
      authLoading.value = false;
    }
  }

  function clearError() {
    authError.value = '';
  }

  function handleLogout() {
    token.value = '';
    currentUser.value = null;
    localStorage.removeItem('accessToken');
  }

  return {
    token, currentUser, authMode, authForm, authLoading, authError,
    isAuthenticated, isAdmin,
    fetchMe, handleAuthSubmit, handleLogout, clearError,
  };
});

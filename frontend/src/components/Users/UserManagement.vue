<script setup lang="ts">
import { ref, onMounted } from 'vue';
import type { UserInfo } from '@/types/user';
import { useAuthStore } from '@/stores/auth';
import api from '@/utils/api';

const authStore = useAuthStore();
const users = ref<UserInfo[]>([]);
const usersLoading = ref(false);

async function fetchUsers() {
  usersLoading.value = true;
  try {
    const response = await api.get<{ users: UserInfo[] }>('/users');
    users.value = response.data.users || [];
  } catch {
    // silently fail
  } finally {
    usersLoading.value = false;
  }
}

async function deleteUser(username: string) {
  if (!confirm(`确定要删除用户 "${username}" 吗？此操作不可撤销，将同时删除该用户的所有聊天记录。`)) return;
  try {
    await api.delete(`/users/${encodeURIComponent(username)}`);
    users.value = users.value.filter(u => u.username !== username);
  } catch (e: unknown) {
    const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '删除失败';
    alert('删除用户失败：' + msg);
  }
}

async function toggleUserRole(user: UserInfo) {
  const newRole = user.role === 'admin' ? 'user' : 'admin';
  const actionLabel = newRole === 'admin' ? '提升为管理员' : '降级为普通用户';
  if (!confirm(`确定要将用户 "${user.username}" ${actionLabel}吗？`)) return;
  try {
    await api.put(`/users/${encodeURIComponent(user.username)}/role`, { role: newRole });
    user.role = newRole;
  } catch (e: unknown) {
    const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '操作失败';
    alert('修改角色失败：' + msg);
  }
}

function formatDate(isoStr: string): string {
  if (!isoStr) return '--';
  try {
    return new Date(isoStr).toLocaleString('zh-CN');
  } catch {
    return isoStr;
  }
}

onMounted(fetchUsers);
</script>

<template>
  <div class="users-stage">
    <div class="stage-header">
      <h2>用户管理</h2>
      <button @click="fetchUsers" class="btn-icon" title="刷新">
        <i class="ph ph-arrows-clockwise"></i>
      </button>
    </div>

    <div v-if="usersLoading" class="loading-state">
      <i class="ph ph-spinner icon-spin"></i> 加载中...
    </div>
    <div v-else-if="!users.length" class="empty-state">
      <p>暂无用户数据</p>
    </div>
    <div v-else class="users-table-wrap">
      <table class="users-table">
        <thead>
          <tr>
            <th>用户名</th>
            <th>角色</th>
            <th>注册时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="user in users" :key="user.username">
            <td>
              {{ user.username }}
              <span v-if="user.username === authStore.currentUser?.username" class="self-tag">当前用户</span>
            </td>
            <td>
              <span :class="['user-role-badge', user.role === 'admin' ? 'admin' : 'user']">
                {{ user.role === 'admin' ? '管理员' : '普通用户' }}
              </span>
            </td>
            <td>{{ formatDate(user.created_at) }}</td>
            <td class="actions-cell">
              <button
                @click="toggleUserRole(user)"
                :disabled="user.username === authStore.currentUser?.username"
                class="btn-glass-sm"
              >
                {{ user.role === 'admin' ? '降级' : '提升' }}
              </button>
              <button
                @click="deleteUser(user.username)"
                :disabled="user.username === authStore.currentUser?.username"
                class="btn-danger-sm"
              >
                删除
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue';
import { useAuthStore } from '@/stores/auth';
import EyeBallCharacter from './EyeBallCharacter.vue';
import PupilCharacter from './PupilCharacter.vue';

const authStore = useAuthStore();

// ---- Mouse tracking for body/face movement ----
const mouseX = ref(0);
const mouseY = ref(0);
function onMouseMove(e: MouseEvent) {
  mouseX.value = e.clientX;
  mouseY.value = e.clientY;
}

onMounted(() => window.addEventListener('mousemove', onMouseMove));
onUnmounted(() => window.removeEventListener('mousemove', onMouseMove));

// ---- Character refs ----
const purpleRef = ref<HTMLElement | null>(null);
const blackRef = ref<HTMLElement | null>(null);
const yellowRef = ref<HTMLElement | null>(null);
const orangeRef = ref<HTMLElement | null>(null);

// ---- Blinking ----
const isPurpleBlinking = ref(false);
const isBlackBlinking = ref(false);

function useRandomBlink(setBlink: (v: boolean) => void) {
  let timer: ReturnType<typeof setTimeout>;
  function schedule() {
    const delay = Math.random() * 4000 + 3000;
    timer = setTimeout(() => {
      setBlink(true);
      setTimeout(() => {
        setBlink(false);
        schedule();
      }, 150);
    }, delay);
  }
  onMounted(() => schedule());
  onUnmounted(() => clearTimeout(timer));
}

useRandomBlink((v) => (isPurpleBlinking.value = v));
useRandomBlink((v) => (isBlackBlinking.value = v));

// ---- Typing state ----
const isTyping = ref(false);
const isLookingAtEachOther = ref(false);
let lookTimer: ReturnType<typeof setTimeout> | null = null;

watch(isTyping, (val) => {
  if (val) {
    isLookingAtEachOther.value = true;
    lookTimer = setTimeout(() => {
      isLookingAtEachOther.value = false;
    }, 1500);
  } else {
    isLookingAtEachOther.value = false;
    if (lookTimer) clearTimeout(lookTimer);
  }
});

// ---- Purple peeking when password is visible ----
const isPurplePeeking = ref(false);
const showPassword = ref(false);
let peekTimer: ReturnType<typeof setTimeout> | null = null;

watch(
  () => authStore.authForm.password,
  (val) => {
    if (val.length > 0 && showPassword.value) {
      function schedulePeek() {
        const delay = Math.random() * 3000 + 2000;
        peekTimer = setTimeout(() => {
          isPurplePeeking.value = true;
          setTimeout(() => {
            isPurplePeeking.value = false;
            if (authStore.authForm.password.length > 0 && showPassword.value) {
              schedulePeek();
            }
          }, 800);
        }, delay);
      }
      schedulePeek();
    } else {
      isPurplePeeking.value = false;
      if (peekTimer) clearTimeout(peekTimer);
    }
  }
);

watch(showPassword, (val) => {
  if (!val) {
    isPurplePeeking.value = false;
    if (peekTimer) clearTimeout(peekTimer);
  }
});

// ---- Calculate face/body position relative to mouse ----
function calcPosition(el: HTMLElement | null) {
  if (!el) return { faceX: 0, faceY: 0, bodySkew: 0 };
  const rect = el.getBoundingClientRect();
  const cx = rect.left + rect.width / 2;
  const cy = rect.top + rect.height / 3;
  const dx = mouseX.value - cx;
  const dy = mouseY.value - cy;
  return {
    faceX: Math.max(-15, Math.min(15, dx / 20)),
    faceY: Math.max(-10, Math.min(10, dy / 30)),
    bodySkew: Math.max(-6, Math.min(6, -dx / 120)),
  };
}

const purplePos = computed(() => calcPosition(purpleRef.value));
const blackPos = computed(() => calcPosition(blackRef.value));
const yellowPos = computed(() => calcPosition(yellowRef.value));
const orangePos = computed(() => calcPosition(orangeRef.value));

// ---- Password visible & typing shortcuts ----
const pw = computed(() => authStore.authForm.password);
const pwVisible = computed(() => showPassword.value);
const isReg = computed(() => authStore.authMode === 'register');

// ---- Computed look direction for characters ----
// Purple: looks at password field when peeking, at black character when looking at each other
const purpleLookX = computed(() => {
  if (pwVisible.value) return isPurplePeeking.value ? 4 : -4;
  if (isLookingAtEachOther.value) return 3;
  return undefined;
});
const purpleLookY = computed(() => {
  if (pwVisible.value) return isPurplePeeking.value ? 5 : -4;
  if (isLookingAtEachOther.value) return 4;
  return undefined;
});

// Black: looks away when password visible, at purple when looking at each other
const blackLookX = computed(() => {
  if (pwVisible.value) return -4;
  if (isLookingAtEachOther.value) return 0;
  return undefined;
});
const blackLookY = computed(() => {
  if (pwVisible.value) return -4;
  if (isLookingAtEachOther.value) return -4;
  return undefined;
});

// Orange & Yellow: look down at password when visible
const bareLookX = computed(() => pwVisible.value ? -5 : undefined);
const bareLookY = computed(() => pwVisible.value ? -4 : undefined);

// ---- Remember me ----
const rememberMe = ref(false);
watch(rememberMe, (val) => {
  authStore.authForm.remember_me = val;
});

// ---- Auto-clear error on input ----
watch(
  () => [authStore.authForm.username, authStore.authForm.password],
  () => {
    if (authStore.authError) authStore.clearError();
  }
);

// ---- Form submit ----
function handleSubmit() {
  authStore.handleAuthSubmit();
}

// ---- Forgot password handler ----
function onForgotPassword() {
  alert('请联系管理员重置密码');
}
</script>

<template>
  <div class="auth-split">
    <!-- ========== LEFT: Characters + Branding ========== -->
    <div class="auth-left">
      <!-- Brand -->
      <div class="auth-left-brand">
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
        <span class="auth-left-name">知渊</span>
      </div>

      <!-- Character stage -->
      <div class="char-stage">
        <!-- Purple tall character (back) -->
        <div
          ref="purpleRef"
          class="char char-purple"
          :style="{
            width: '180px',
            height: (isTyping || (pw.length > 0 && !pwVisible)) ? '440px' : '400px',
            transform: pwVisible
              ? 'skewX(0deg)'
              : (isTyping || (pw.length > 0 && !pwVisible))
                ? `skewX(${(purplePos.bodySkew || 0) - 12}deg) translateX(40px)`
                : `skewX(${purplePos.bodySkew || 0}deg)`,
            zIndex: 1,
          }"
        >
          <div
            class="char-eyes"
            :style="{
              left: pwVisible ? '20px' : isLookingAtEachOther ? '55px' : `${45 + purplePos.faceX}px`,
              top: pwVisible ? '35px' : isLookingAtEachOther ? '65px' : `${40 + purplePos.faceY}px`,
              gap: '32px',
            }"
          >
            <EyeBallCharacter
              :size="18"
              :pupil-size="7"
              :max-distance="5"
              eye-color="white"
              pupil-color="#2D2D2D"
              :blinking="isPurpleBlinking"
              :force-look-x="purpleLookX"
              :force-look-y="purpleLookY"
            />
            <EyeBallCharacter
              :size="18"
              :pupil-size="7"
              :max-distance="5"
              eye-color="white"
              pupil-color="#2D2D2D"
              :blinking="isPurpleBlinking"
              :force-look-x="purpleLookX"
              :force-look-y="purpleLookY"
            />
          </div>
        </div>

        <!-- Black tall character (middle) -->
        <div
          ref="blackRef"
          class="char char-black"
          :style="{
            width: '120px',
            height: '310px',
            transform: pwVisible
              ? 'skewX(0deg)'
              : isLookingAtEachOther
                ? `skewX(${(blackPos.bodySkew || 0) * 1.5 + 10}deg) translateX(20px)`
                : (isTyping || (pw.length > 0 && !pwVisible))
                  ? `skewX(${(blackPos.bodySkew || 0) * 1.5}deg)`
                  : `skewX(${blackPos.bodySkew || 0}deg)`,
            zIndex: 2,
          }"
        >
          <div
            class="char-eyes"
            :style="{
              left: pwVisible ? '10px' : isLookingAtEachOther ? '32px' : `${26 + blackPos.faceX}px`,
              top: pwVisible ? '28px' : isLookingAtEachOther ? '12px' : `${32 + blackPos.faceY}px`,
              gap: '24px',
            }"
          >
            <EyeBallCharacter
              :size="16"
              :pupil-size="6"
              :max-distance="4"
              eye-color="white"
              pupil-color="#2D2D2D"
              :blinking="isBlackBlinking"
              :force-look-x="blackLookX"
              :force-look-y="blackLookY"
            />
            <EyeBallCharacter
              :size="16"
              :pupil-size="6"
              :max-distance="4"
              eye-color="white"
              pupil-color="#2D2D2D"
              :blinking="isBlackBlinking"
              :force-look-x="blackLookX"
              :force-look-y="blackLookY"
            />
          </div>
        </div>

        <!-- Orange semi-circle (front left) -->
        <div
          ref="orangeRef"
          class="char char-orange"
          :style="{
            width: '240px',
            height: '200px',
            transform: pwVisible ? 'skewX(0deg)' : `skewX(${orangePos.bodySkew || 0}deg)`,
            zIndex: 3,
          }"
        >
          <div
            class="char-eyes bare-eyes"
            :style="{
              left: pwVisible ? '50px' : `${82 + (orangePos.faceX || 0)}px`,
              top: pwVisible ? '85px' : `${90 + (orangePos.faceY || 0)}px`,
              gap: '32px',
            }"
          >
            <PupilCharacter
              :size="12"
              :max-distance="5"
              pupil-color="#2D2D2D"
              :force-look-x="bareLookX"
              :force-look-y="bareLookY"
            />
            <PupilCharacter
              :size="12"
              :max-distance="5"
              pupil-color="#2D2D2D"
              :force-look-x="bareLookX"
              :force-look-y="bareLookY"
            />
          </div>
        </div>

        <!-- Yellow semi-circle (front right) -->
        <div
          ref="yellowRef"
          class="char char-yellow"
          :style="{
            width: '140px',
            height: '230px',
            transform: pwVisible ? 'skewX(0deg)' : `skewX(${yellowPos.bodySkew || 0}deg)`,
            zIndex: 4,
          }"
        >
          <div
            class="char-eyes bare-eyes"
            :style="{
              left: pwVisible ? '20px' : `${52 + (yellowPos.faceX || 0)}px`,
              top: pwVisible ? '35px' : `${40 + (yellowPos.faceY || 0)}px`,
              gap: '24px',
            }"
          >
            <PupilCharacter
              :size="12"
              :max-distance="5"
              pupil-color="#2D2D2D"
              :force-look-x="bareLookX"
              :force-look-y="bareLookY"
            />
            <PupilCharacter
              :size="12"
              :max-distance="5"
              pupil-color="#2D2D2D"
              :force-look-x="bareLookX"
              :force-look-y="bareLookY"
            />
          </div>
          <!-- Mouth line -->
          <div
            class="char-mouth"
            :style="{
              left: pwVisible ? '10px' : `${40 + (yellowPos.faceX || 0)}px`,
              top: pwVisible ? '88px' : `${88 + (yellowPos.faceY || 0)}px`,
            }"
          />
        </div>
      </div>

      <!-- Footer links -->
      <div class="auth-left-footer">
        <a href="#">隐私政策</a>
        <a href="#">服务条款</a>
        <a href="#">联系我们</a>
      </div>
    </div>

    <!-- ========== RIGHT: Login / Register Form ========== -->
    <div class="auth-right">
      <div class="auth-card">
        <!-- Mobile brand -->
        <div class="auth-card-mobile-brand">
          <div class="brand-mark-sm">
            <svg viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M24 6 L38 20 L38 38 L28 38 L28 26 L20 26 L20 38 L10 38 L10 20 Z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/>
              <circle cx="24" cy="18" r="5" stroke="currentColor" stroke-width="1.5"/>
              <circle cx="22" cy="17" r="1.5" fill="currentColor"/>
              <circle cx="27" cy="17" r="1.5" fill="currentColor"/>
            </svg>
          </div>
          <span>知渊</span>
        </div>

        <!-- Header -->
        <div class="auth-card-header">
          <h1>{{ isReg ? '创建账号' : '欢迎回来！' }}</h1>
          <p>{{ isReg ? '填写信息加入知渊' : '请输入您的账号信息' }}</p>
        </div>

        <!-- Form -->
        <form @submit.prevent="handleSubmit" class="auth-form">
          <!-- Username -->
          <div class="field">
            <label>用户名</label>
            <input
              v-model="authStore.authForm.username"
              type="text"
              placeholder="输入用户名"
              autocomplete="username"
              @focus="isTyping = true"
              @blur="isTyping = false"
              required
            />
          </div>

          <!-- Password -->
          <div class="field">
            <label>密码</label>
            <div class="pw-wrap">
              <input
                v-model="authStore.authForm.password"
                :type="showPassword ? 'text' : 'password'"
                placeholder="••••••••"
                autocomplete="current-password"
                required
              />
              <button
                type="button"
                class="pw-toggle"
                @click="showPassword = !showPassword"
                :title="showPassword ? '隐藏密码' : '显示密码'"
              >
                <!-- Eye icon -->
                <svg v-if="!showPassword" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
                  <circle cx="12" cy="12" r="3"/>
                </svg>
                <svg v-else width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/>
                  <path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/>
                  <path d="m14.12 14.12a3 3 0 1 1-4.24-4.24"/>
                  <line x1="1" y1="1" x2="23" y2="23"/>
                </svg>
              </button>
            </div>
          </div>

          <!-- Register-only fields -->
          <template v-if="isReg">
            <div class="field">
              <label>角色</label>
              <select v-model="authStore.authForm.role">
                <option value="user">普通用户</option>
                <option value="admin">管理员</option>
              </select>
            </div>
            <div v-if="authStore.authForm.role === 'admin'" class="field">
              <label>管理员邀请码</label>
              <input
                v-model="authStore.authForm.admin_code"
                type="text"
                placeholder="输入邀请码"
              />
            </div>
          </template>

          <!-- Remember me + Forgot password -->
          <div class="form-options">
            <label class="checkbox-label">
              <input type="checkbox" v-model="rememberMe" />
              <span class="checkbox-custom">
                <svg v-if="rememberMe" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
                  <polyline points="20 6 9 17 4 12"/>
                </svg>
              </span>
              <span>记住我（30天）</span>
            </label>
            <a
              href="#"
              class="forgot-password"
              @click.prevent="onForgotPassword"
            >忘记密码？</a>
          </div>

          <!-- Error display -->
          <div v-if="authStore.authError" class="auth-error">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="10"/>
              <line x1="12" y1="8" x2="12" y2="12"/>
              <line x1="12" y1="16" x2="12.01" y2="16"/>
            </svg>
            <span>{{ authStore.authError }}</span>
          </div>

          <!-- Submit button -->
          <button
            type="submit"
            class="btn-submit"
            :disabled="authStore.authLoading"
          >
            <span v-if="authStore.authLoading" class="spinner" />
            {{ authStore.authLoading ? '处理中...' : isReg ? '注册' : '登录' }}
          </button>

          <!-- Toggle mode -->
          <p class="auth-toggle">
            {{ isReg ? '已有账号？' : '还没有账号？' }}
            <a
              href="#"
              @click.prevent="authStore.authMode = isReg ? 'login' : 'register'"
            >
              {{ isReg ? '去登录' : '立即注册' }}
            </a>
          </p>
        </form>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* ================================================================
   AUTH SPLIT LAYOUT
   ================================================================ */
.auth-split {
  display: grid;
  grid-template-columns: 1fr 1fr;
  flex: 1;
  width: 100%;
}

/* ---- LEFT: Characters Panel ---- */
.auth-left {
  position: relative;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  background: linear-gradient(160deg, #ffffff 0%, #faf5ff 25%, #f3e8ff 50%, #f0e6fc 100%);
  padding: 40px 28px;
  overflow: hidden;
}

/* Decorative overlays */
.auth-left::before {
  content: '';
  position: absolute;
  inset: 0;
  background:
    radial-gradient(ellipse 60% 50% at 30% 60%, rgba(108, 63, 245, 0.08) 0%, transparent 70%),
    radial-gradient(ellipse 40% 40% at 70% 30%, rgba(108, 63, 245, 0.04) 0%, transparent 70%);
  pointer-events: none;
}

.auth-left::after {
  content: '';
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(0,0,0,0.04) 1px, transparent 1px),
    linear-gradient(90deg, rgba(0,0,0,0.04) 1px, transparent 1px);
  background-size: 24px 24px;
  pointer-events: none;
}

.auth-left-brand {
  position: relative;
  z-index: 10;
  display: flex;
  align-items: center;
  gap: 10px;
}

.auth-left-name {
  font-family: var(--font-display);
  font-size: 1.25rem;
  font-weight: 600;
  color: #4c1d95;
}

.auth-left-footer {
  position: relative;
  z-index: 10;
  display: flex;
  gap: 24px;
}

.auth-left-footer a {
  font-size: 0.78rem;
  color: rgba(0,0,0,0.35);
  text-decoration: none;
  transition: color 0.2s;
}

.auth-left-footer a:hover {
  color: rgba(0,0,0,0.65);
}

/* ---- Character Stage ---- */
.char-stage {
  position: relative;
  width: 480px;
  height: 360px;
  margin: auto;
  z-index: 5;
}

/* ---- Character Base ---- */
.char {
  position: absolute;
  bottom: 0;
  transition: all 0.7s ease-in-out;
  transform-origin: bottom center;
}

.char-purple {
  left: 70px;
  background: #6C3FF5;
  border-radius: 10px 10px 0 0;
}

.char-black {
  left: 240px;
  background: #2D2D2D;
  border-radius: 8px 8px 0 0;
}

.char-orange {
  left: 0;
  background: #FF9B6B;
  border-radius: 120px 120px 0 0;
}

.char-yellow {
  left: 310px;
  background: #E8D754;
  border-radius: 70px 70px 0 0;
}

/* ---- Eyes container ---- */
.char-eyes {
  position: absolute;
  display: flex;
  transition: all 0.7s ease-in-out;
}

/* Bare eyes container (orange & yellow) */
.bare-eyes {
  /* pupils are rendered by PupilCharacter */
}

/* ---- Mouth ---- */
.char-mouth {
  position: absolute;
  width: 80px;
  height: 4px;
  background: #2D2D2D;
  border-radius: 2px;
  transition: all 0.2s ease-out;
}

/* ================================================================
   RIGHT: Login Form
   ================================================================ */
.auth-right {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px;
  background: #fafafa;
  overflow-y: auto;
}

.auth-card {
  width: 420px;
  max-width: 100%;
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.auth-card-mobile-brand {
  display: none;
  align-items: center;
  justify-content: center;
  gap: 8px;
  font-family: var(--font-display);
  font-size: 1.2rem;
  font-weight: 600;
  color: #1a1a2e;
}

.brand-mark-sm {
  width: 36px;
  height: 36px;
  color: #7c3aed;
}

.brand-mark-sm svg,
.brand-mark-lg svg {
  width: 100%;
  height: 100%;
}

.auth-card-header {
  text-align: center;
}

.auth-card-header h1 {
  font-family: var(--font-display);
  font-size: 1.8rem;
  font-weight: 600;
  color: #1a1a2e;
  margin-bottom: 6px;
}

.auth-card-header p {
  font-size: 0.9rem;
  color: #6b7280;
}

/* ---- Form ---- */
.auth-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.field label {
  font-size: 0.8rem;
  font-weight: 600;
  color: #4b5563;
}

.field input,
.field select {
  padding: 12px 16px;
  background: #f9fafb;
  border: 1px solid #e5e7eb;
  border-radius: var(--radius-md);
  color: #1a1a2e;
  font-family: var(--font-body);
  font-size: 0.92rem;
  outline: none;
  transition: all 0.18s var(--ease-out);
}

.field input::placeholder {
  color: #9ca3af;
}

.field input:focus,
.field select:focus {
  border-color: #7c3aed;
  box-shadow: 0 0 0 4px rgba(124, 58, 237, 0.12);
  background: #ffffff;
}

.field select {
  cursor: pointer;
  appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' fill='%239ca3af' viewBox='0 0 256 256'%3E%3Cpath d='M213.66,101.66l-80,80a8,8,0,0,1-11.32,0l-80-80A8,8,0,0,1,48,88H208a8,8,0,0,1,5.66,13.66Z'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 12px center;
  padding-right: 36px;
}

/* ---- Password wrapper ---- */
.pw-wrap {
  position: relative;
}

.pw-wrap input {
  width: 100%;
  padding-right: 44px;
}

.pw-toggle {
  position: absolute;
  right: 12px;
  top: 50%;
  transform: translateY(-50%);
  background: none;
  border: none;
  color: #9ca3af;
  cursor: pointer;
  padding: 4px;
  display: flex;
  align-items: center;
  transition: color 0.2s;
}

.pw-toggle:hover {
  color: #4b5563;
}

/* ---- Remember me + Forgot password row ---- */
.form-options {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 2px;
}

.checkbox-label {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  font-size: 0.85rem;
  color: #4b5563;
  user-select: none;
}

.checkbox-label input[type="checkbox"] {
  position: absolute;
  opacity: 0;
  width: 0;
  height: 0;
  pointer-events: none;
}

.checkbox-custom {
  width: 18px;
  height: 18px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid #e5e7eb;
  border-radius: 4px;
  background: #f9fafb;
  transition: all 0.18s var(--ease-out);
  flex-shrink: 0;
}

.checkbox-label input:checked + .checkbox-custom {
  background: #7c3aed;
  border-color: #7c3aed;
  color: #ffffff;
}

.checkbox-label:hover .checkbox-custom {
  border-color: #7c3aed;
}

.forgot-password {
  font-size: 0.85rem;
  color: #6b7280;
  text-decoration: none;
  transition: color 0.2s;
}

.forgot-password:hover {
  color: #7c3aed;
  text-decoration: underline;
}

/* ---- Error display ---- */
.auth-error {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: var(--radius-md);
  color: #dc2626;
  font-size: 0.88rem;
  animation: errorSlideIn 0.25s var(--ease-out);
}

.auth-error svg {
  flex-shrink: 0;
  color: #ef4444;
}

@keyframes errorSlideIn {
  from {
    opacity: 0;
    transform: translateY(-6px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* ---- Submit button ---- */
.btn-submit {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 13px 22px;
  margin-top: 4px;
  background: #7c3aed;
  color: #ffffff;
  border: 1px solid #7c3aed;
  border-radius: var(--radius-md);
  font-family: var(--font-body);
  font-size: 0.95rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.3s var(--ease-bounce);
  letter-spacing: 0.02em;
}

.btn-submit:hover:not(:disabled) {
  background: #6d28d9;
  border-color: #6d28d9;
  color: #ffffff;
  transform: translateY(-2px) scale(1.02);
  box-shadow: 0 8px 28px rgba(124, 58, 237, 0.3);
}

.btn-submit:active:not(:disabled) {
  transform: translateY(0) scale(0.97);
  transition: all 0.1s var(--ease-out);
}

.btn-submit:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

/* ---- Spinner ---- */
.spinner {
  width: 18px;
  height: 18px;
  border: 2px solid rgba(255,255,255,0.3);
  border-top-color: #ffffff;
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* ---- Toggle link ---- */
.auth-toggle {
  text-align: center;
  font-size: 0.88rem;
  color: #6b7280;
}

.auth-toggle a {
  color: #7c3aed;
  font-weight: 600;
  text-decoration: none;
  transition: color 0.2s;
}

.auth-toggle a:hover {
  color: #6d28d9;
  text-decoration: underline;
}

/* ================================================================
   BRAND ICON
   ================================================================ */
.brand-mark-lg {
  width: 44px;
  height: 44px;
  color: #7c3aed;
  animation: markPulse 3s ease-in-out infinite;
}

@keyframes markPulse {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.06); }
}

/* ================================================================
   RESPONSIVE
   ================================================================ */
@media (max-width: 900px) {
  .auth-split {
    grid-template-columns: 1fr;
  }

  .auth-left {
    display: none;
  }

  .auth-right {
    padding: 24px 20px;
  }

  .auth-card-mobile-brand {
    display: flex;
    margin-bottom: 12px;
  }
}
</style>

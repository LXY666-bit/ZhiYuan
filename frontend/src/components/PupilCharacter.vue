<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue';

const props = withDefaults(
  defineProps<{
    size?: number;
    maxDistance?: number;
    pupilColor?: string;
    forceLookX?: number;
    forceLookY?: number;
  }>(),
  {
    size: 12,
    maxDistance: 5,
    pupilColor: '#2D2D2D',
  },
);

const mouseX = ref(0);
const mouseY = ref(0);
const pupilRef = ref<HTMLElement | null>(null);

function onMouseMove(e: MouseEvent) {
  mouseX.value = e.clientX;
  mouseY.value = e.clientY;
}

onMounted(() => window.addEventListener('mousemove', onMouseMove));
onUnmounted(() => window.removeEventListener('mousemove', onMouseMove));

const pupilPosition = computed(() => {
  if (!pupilRef.value) return { x: 0, y: 0 };

  // If forced look direction is provided, use that instead of mouse tracking
  if (props.forceLookX !== undefined && props.forceLookY !== undefined) {
    return { x: props.forceLookX, y: props.forceLookY };
  }

  const rect = pupilRef.value.getBoundingClientRect();
  const cx = rect.left + rect.width / 2;
  const cy = rect.top + rect.height / 2;

  const dx = mouseX.value - cx;
  const dy = mouseY.value - cy;
  const dist = Math.min(Math.sqrt(dx ** 2 + dy ** 2), props.maxDistance);

  const angle = Math.atan2(dy, dx);
  return {
    x: Math.cos(angle) * dist,
    y: Math.sin(angle) * dist,
  };
});
</script>

<template>
  <div
    ref="pupilRef"
    class="pupil-dot"
    :style="{
      width: `${size}px`,
      height: `${size}px`,
      backgroundColor: pupilColor,
      transform: `translate(${pupilPosition.x}px, ${pupilPosition.y}px)`,
    }"
  />
</template>

<style scoped>
.pupil-dot {
  border-radius: 50%;
  transition: transform 0.08s ease-out;
}
</style>

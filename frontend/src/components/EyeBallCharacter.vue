<script setup lang="ts">
import PupilCharacter from './PupilCharacter.vue';

withDefaults(
  defineProps<{
    size?: number;
    pupilSize?: number;
    maxDistance?: number;
    eyeColor?: string;
    pupilColor?: string;
    blinking?: boolean;
    forceLookX?: number;
    forceLookY?: number;
  }>(),
  {
    size: 48,
    pupilSize: 16,
    maxDistance: 10,
    eyeColor: 'white',
    pupilColor: '#2D2D2D',
    blinking: false,
  },
);
</script>

<template>
  <div
    class="eye-white"
    :class="{ blinking }"
    :style="{
      width: `${size}px`,
      height: blinking ? '2px' : `${size}px`,
      backgroundColor: eyeColor,
    }"
  >
    <PupilCharacter
      v-if="!blinking"
      :size="pupilSize"
      :max-distance="maxDistance"
      :pupil-color="pupilColor"
      :force-look-x="forceLookX"
      :force-look-y="forceLookY"
    />
  </div>
</template>

<style scoped>
.eye-white {
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  transition: height 0.15s;
}
</style>

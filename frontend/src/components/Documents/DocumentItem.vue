<script setup lang="ts">
import { useDocumentStore } from '@/stores/documents';

const props = defineProps<{
  filename: string;
  fileType: string;
  chunkCount: number;
  selected: boolean;
}>();

const docStore = useDocumentStore();
</script>

<template>
  <div :class="['doc-row', { deleting: docStore.isDeletingDocument(props.filename) }]">
    <div class="doc-main">
      <input
        type="checkbox"
        :checked="props.selected"
        @change="docStore.toggleDocSelection(props.filename)"
        class="doc-checkbox"
      />
      <i :class="docStore.getFileIcon(props.fileType)"></i>
      <div class="doc-info">
        <span class="doc-name">{{ props.filename }}</span>
        <span class="doc-meta">{{ props.fileType }} · {{ props.chunkCount }} chunks</span>
      </div>
    </div>
    <div class="doc-actions">
      <button
        @click="docStore.deleteDocument(props.filename)"
        :disabled="docStore.isDeletingDocument(props.filename)"
        class="btn-delete"
        :title="docStore.isDeletingDocument(props.filename) ? '删除中...' : '删除'"
      >
        <i v-if="docStore.isDeletingDocument(props.filename)" class="ph ph-spinner icon-spin"></i>
        <i v-else class="ph ph-trash"></i>
      </button>
    </div>
  </div>
  <!-- Delete progress -->
  <div v-if="docStore.deleteJobs[props.filename]" class="doc-delete-progress">
    <div
      v-for="step in (docStore.deleteJobs[props.filename].steps || [])"
      :key="step.key"
      class="progress-step"
    >
      <div class="step-indicator" :class="step.status">
        <i v-if="step.status === 'completed'" class="ph ph-check"></i>
        <i v-else-if="step.status === 'running'" class="ph ph-spinner icon-spin"></i>
        <i v-else-if="step.status === 'failed'" class="ph ph-x"></i>
        <span v-else class="step-dot"></span>
      </div>
      <div class="step-info">
        <span class="step-label">{{ step.label }}</span>
        <div class="step-bar">
          <div class="step-fill" :class="step.status" :style="{ width: step.percent + '%' }"></div>
        </div>
      </div>
      <span class="step-pct">{{ step.percent }}%</span>
    </div>
  </div>
</template>

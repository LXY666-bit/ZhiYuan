<script setup lang="ts">
import { ref } from 'vue';
import { useDocumentStore } from '@/stores/documents';

const docStore = useDocumentStore();
const fileInput = ref<HTMLInputElement | null>(null);

function handleFileSelect(event: Event) {
  const input = event.target as HTMLInputElement;
  const files = input.files;
  if (!files || files.length === 0) return;
  if (files.length === 1) {
    docStore.selectedFile = files[0];
    docStore.uploadSteps = docStore.createUploadSteps();
    docStore.uploadProgressCollapsed = false;
    docStore.batchFiles = [];
  } else {
    docStore.selectedFile = null;
    docStore.batchFiles = Array.from(files).map(file => ({
      file,
      status: 'pending' as const,
      jobId: '',
      message: '',
      steps: docStore.createUploadSteps(),
      collapsed: false,
      xhr: null,
      pollTimer: null,
    }));
  }
}

function handleDrop(event: DragEvent) {
  event.preventDefault();
  const files = event.dataTransfer?.files;
  if (!files || files.length === 0) return;
  if (files.length === 1) {
    docStore.selectedFile = files[0];
    docStore.uploadSteps = docStore.createUploadSteps();
    docStore.uploadProgressCollapsed = false;
    docStore.batchFiles = [];
  } else {
    docStore.selectedFile = null;
    docStore.batchFiles = Array.from(files).map(file => ({
      file,
      status: 'pending' as const,
      jobId: '',
      message: '',
      steps: docStore.createUploadSteps(),
      collapsed: false,
      xhr: null,
      pollTimer: null,
    }));
  }
}
</script>

<template>
  <div class="upload-zone" @drop.prevent="handleDrop" @dragover.prevent>
    <div class="upload-zone-inner">
      <i class="ph ph-cloud-arrow-up upload-zone-icon"></i>
      <p>拖拽文件到此处，或点击选择</p>
      <p class="upload-zone-hint">支持 PDF、Word、Excel、TXT 格式</p>
      <input
        ref="fileInput"
        type="file"
        accept=".pdf,.doc,.docx,.xls,.xlsx,.txt"
        multiple
        @change="handleFileSelect"
        hidden
      />
      <button @click="fileInput?.click()" class="btn-glass">选择文件</button>
    </div>
  </div>

  <!-- Single file upload -->
  <div v-if="docStore.selectedFile" class="upload-card">
    <div class="upload-card-header">
      <span>{{ docStore.selectedFile.name }}</span>
      <button
        v-if="!docStore.isUploading"
        @click="docStore.uploadDocument()"
        class="btn-glass"
      >上传</button>
    </div>
    <div v-if="docStore.isUploading" class="upload-progress">
      <div v-for="step in docStore.uploadSteps" :key="step.key" class="progress-step">
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
  </div>

  <!-- Batch upload list -->
  <div v-if="docStore.batchFiles.length" class="batch-list">
    <div class="batch-header">
      <span>批量上传（{{ docStore.batchSummary }}）</span>
      <button
        v-if="!docStore.isUploading"
        @click="() => {
          docStore.isUploading = true;
          docStore.batchFiles.forEach((_bf, idx) => {
            if (docStore.batchFiles[idx].status === 'pending') {
              // handled by document store
            }
          });
        }"
        class="btn-glass"
      >全部上传</button>
    </div>
    <div v-for="(bf, idx) in docStore.batchFiles" :key="idx" class="batch-item">
      <span class="batch-filename">{{ bf.file.name }}</span>
      <span class="batch-status" :class="bf.status">{{ docStore.batchFileStatusLabel(bf) }}</span>
    </div>
  </div>
</template>

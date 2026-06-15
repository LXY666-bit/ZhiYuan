<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue';
import { useDocumentStore } from '@/stores/documents';
import UploadSection from './UploadSection.vue';
import DocumentItem from './DocumentItem.vue';

const docStore = useDocumentStore();

onMounted(() => {
  docStore.loadDocuments();
});

onUnmounted(() => {
  docStore.cleanup();
});
</script>

<template>
  <div class="settings-stage">
    <div class="stage-header">
      <h2>知识库管理</h2>
      <button @click="docStore.loadDocuments()" class="btn-icon" title="刷新">
        <i class="ph ph-arrows-clockwise"></i>
      </button>
    </div>

    <UploadSection />

    <!-- Document list -->
    <div class="panel">
      <div class="doc-list-header">
        <h3><i class="ph ph-files"></i> 已索引文档（{{ docStore.documents.length }}）</h3>
        <button @click="docStore.loadDocuments()" class="btn-icon btn-sm" title="刷新列表">
          <i class="ph ph-arrows-clockwise"></i>
        </button>
      </div>

      <!-- Batch action bar -->
      <div v-if="docStore.selectedDocsCount > 0" class="batch-action-bar">
        <label class="checkbox-label">
          <input type="checkbox" :checked="docStore.allDocsSelected" @change="docStore.toggleSelectAll()" />
          <span>全选（{{ docStore.selectedDocsCount }}）</span>
        </label>
        <button @click="docStore.batchDeleteDocuments()" class="btn-danger">
          <i class="ph ph-trash"></i>
          批量删除
        </button>
      </div>

      <div class="panel-body" style="padding: 0;">
        <div v-if="docStore.documentsLoading" class="loading-state">
          <i class="ph ph-spinner icon-spin"></i> 加载中...
        </div>
        <div v-else-if="!docStore.documents.length" class="empty-state">
          <i class="ph ph-archive-tray"></i>
          <p>尚未上传任何文档</p>
        </div>
        <div v-else class="doc-list">
          <DocumentItem
            v-for="doc in docStore.documents"
            :key="doc.filename"
            :filename="doc.filename"
            :file-type="doc.file_type"
            :chunk-count="doc.chunk_count"
            :selected="docStore.selectedDocs.has(doc.filename)"
          />
        </div>
      </div>
    </div>
  </div>
</template>

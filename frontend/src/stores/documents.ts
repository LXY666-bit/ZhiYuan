import { defineStore } from 'pinia';
import { ref, computed } from 'vue';
import type { DocumentItem, UploadStep, DeleteStep, ActiveDeleteJob, BatchFile, UploadJob } from '@/types/document';
import api from '@/utils/api';
import { useAuthStore } from './auth';

function createUploadSteps(): UploadStep[] {
  return [
    { key: 'upload', label: '文件上传', percent: 0, status: 'pending', message: '' },
    { key: 'cleanup', label: '清理旧版本', percent: 0, status: 'pending', message: '' },
    { key: 'parse', label: '文档解析与分块', percent: 0, status: 'pending', message: '' },
    { key: 'parent_store', label: '父级分块入库', percent: 0, status: 'pending', message: '' },
    { key: 'vector_store', label: '向量化索引', percent: 0, status: 'pending', message: '' },
  ];
}

function createDeleteSteps(): DeleteStep[] {
  return [
    { key: 'prepare', label: '准备删除', percent: 0, status: 'pending', message: '' },
    { key: 'bm25', label: '同步 BM25 统计', percent: 0, status: 'pending', message: '' },
    { key: 'milvus', label: '删除向量数据', percent: 0, status: 'pending', message: '' },
    { key: 'parent_store', label: '删除父级分块', percent: 0, status: 'pending', message: '' },
  ];
}

export const useDocumentStore = defineStore('documents', () => {
  // ── State ──
  const documents = ref<DocumentItem[]>([]);
  const documentsLoading = ref(false);
  const selectedFile = ref<File | null>(null);
  const isUploading = ref(false);
  const uploadSteps = ref<UploadStep[]>(createUploadSteps());
  const uploadProgressCollapsed = ref(false);
  const activeUploadJobId = ref('');
  let uploadPollTimer: ReturnType<typeof setInterval> | null = null;

  // Batch upload
  const batchFiles = ref<BatchFile[]>([]);
  // Batch delete
  const selectedDocs = ref<Set<string>>(new Set());

  // Delete jobs
  const deleteJobs = ref<Record<string, ActiveDeleteJob>>({});
  const deletePollTimers: Record<string, ReturnType<typeof setInterval>> = {};
  const deleteRemoveTimers: Record<string, ReturnType<typeof setTimeout>> = {};

  // ── Computed ──
  const allDocsSelected = computed(() =>
    documents.value.length > 0 && selectedDocs.value.size === documents.value.length
  );
  const selectedDocsCount = computed(() => selectedDocs.value.size);
  const batchSummary = computed(() => {
    if (!batchFiles.value.length) return '';
    const completed = batchFiles.value.filter(f => f.status === 'completed').length;
    const failed = batchFiles.value.filter(f => f.status === 'failed').length;
    const cancelled = batchFiles.value.filter(f => f.status === 'cancelled').length;
    const uploading = batchFiles.value.filter(f => f.status === 'uploading' || f.status === 'running').length;
    let s = `${completed}/${batchFiles.value.length} 完成`;
    if (failed) s += `，${failed} 失败`;
    if (cancelled) s += `，${cancelled} 已取消`;
    if (uploading) s += `，${uploading} 处理中`;
    return s;
  });

  // ── Document List ──
  async function loadDocuments() {
    documentsLoading.value = true;
    try {
      const response = await api.get<{ documents: DocumentItem[] }>('/documents');
      // Merge with active delete jobs
      const remoteDocs = response.data.documents || [];
      const merged = [...remoteDocs];
      Object.keys(deleteJobs.value).forEach(fn => {
        const j = deleteJobs.value[fn];
        if (!j || j.status === 'failed') return;
        if (!merged.some(d => d.filename === fn)) {
          const cur = documents.value.find(d => d.filename === fn);
          if (cur) merged.push(cur);
        }
      });
      documents.value = merged;
    } catch {
      // silently fail
    } finally {
      documentsLoading.value = false;
    }
  }

  // ── Single Upload ──
  function updateUploadStep(key: string, percent: number, status: UploadStep['status'] = 'running', message = '') {
    const idx = uploadSteps.value.findIndex(s => s.key === key);
    if (idx === -1) return;
    uploadSteps.value[idx] = {
      ...uploadSteps.value[idx],
      percent: Math.max(0, Math.min(100, Math.round(percent || 0))),
      status, message,
    };
  }

  function uploadFileWithProgress(file: File): Promise<{ job_id: string; message: string }> {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      const fd = new FormData();
      fd.append('file', file);
      xhr.open('POST', '/documents/upload/async');
      const token = localStorage.getItem('accessToken');
      if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`);
      xhr.upload.onprogress = (e) => {
        if (!e.lengthComputable) return;
        const pct = Math.round((e.loaded / e.total) * 100);
        updateUploadStep('upload', pct, 'running', `已上传 ${pct}%`);
      };
      xhr.onload = () => {
        if (xhr.status === 401) { reject(new Error('登录已过期')); return; }
        let data: { job_id?: string; message?: string; detail?: string } = {};
        try { data = JSON.parse(xhr.responseText || '{}'); } catch { reject(new Error('响应解析失败')); return; }
        if (xhr.status < 200 || xhr.status >= 300) { reject(new Error(data.detail || `HTTP ${xhr.status}`)); return; }
        updateUploadStep('upload', 100, 'completed', '文件已保存');
        resolve({ job_id: data.job_id || '', message: data.message || '' });
      };
      xhr.onerror = () => reject(new Error('上传请求失败'));
      xhr.onabort = () => reject(new Error('上传已取消'));
      xhr.send(fd);
    });
  }

  function stopUploadJobPolling() {
    if (uploadPollTimer) { clearInterval(uploadPollTimer); uploadPollTimer = null; }
  }

  function startUploadJobPolling(jobId: string) {
    stopUploadJobPolling();
    const poll = async () => {
      try {
        const response = await api.get<UploadJob>(`/documents/upload/jobs/${encodeURIComponent(jobId)}`);
        const job = response.data;
        activeUploadJobId.value = job.job_id;
        if (Array.isArray(job.steps)) {
          uploadSteps.value = job.steps.map(s => ({
            key: s.key, label: s.label, percent: s.percent, status: s.status, message: s.message || '',
          }));
        }
        if (job.status === 'completed') {
          stopUploadJobPolling();
          isUploading.value = false;
          selectedFile.value = null;
          uploadProgressCollapsed.value = true;
          await loadDocuments();
        } else if (job.status === 'failed') {
          stopUploadJobPolling();
          isUploading.value = false;
        }
      } catch {
        stopUploadJobPolling();
        isUploading.value = false;
      }
    };
    poll();
    uploadPollTimer = setInterval(poll, 1000);
  }

  async function uploadDocument() {
    if (!selectedFile.value) { alert('请先选择文件'); return; }
    isUploading.value = true;
    uploadSteps.value = createUploadSteps();
    uploadProgressCollapsed.value = false;
    updateUploadStep('upload', 0, 'running', '准备上传');
    try {
      const data = await uploadFileWithProgress(selectedFile.value);
      activeUploadJobId.value = data.job_id;
      startUploadJobPolling(data.job_id);
    } catch (e: unknown) {
      updateUploadStep('upload', 100, 'failed', (e as Error).message);
      isUploading.value = false;
    }
  }

  // ── Delete ──
  function isDeletingDocument(filename: string): boolean {
    const j = deleteJobs.value[filename];
    return !!(j && j.status === 'running');
  }

  function setDeleteJob(filename: string, next: Partial<ActiveDeleteJob>) {
    deleteJobs.value = { ...deleteJobs.value, [filename]: { ...(deleteJobs.value[filename] || {} as ActiveDeleteJob), ...next } };
  }

  function stopDeletePolling(filename: string) {
    const t = deletePollTimers[filename];
    if (!t) return;
    clearInterval(t);
    delete deletePollTimers[filename];
  }

  function startDeleteJobPolling(filename: string, jobId: string) {
    stopDeletePolling(filename);
    const poll = async () => {
      try {
        const response = await api.get(`/documents/delete/jobs/${encodeURIComponent(jobId)}`);
        const job = response.data;
        setDeleteJob(filename, {
          jobId: job.job_id, status: job.status, message: job.message || '',
          collapsed: job.status === 'completed' ? true : !!(deleteJobs.value[filename]?.collapsed),
          steps: Array.isArray(job.steps) ? job.steps.map((s: DeleteStep) => ({
            key: s.key, label: s.label, percent: s.percent, status: s.status, message: s.message || '',
          })) : createDeleteSteps(),
        });
        if (job.status === 'completed') {
          stopDeletePolling(filename);
          // Remove after 3 seconds
          deleteRemoveTimers[filename] = setTimeout(async () => {
            documents.value = documents.value.filter(d => d.filename !== filename);
            const { [filename]: _j, ...jobs } = deleteJobs.value;
            deleteJobs.value = jobs;
            await loadDocuments();
          }, 3000);
        } else if (job.status === 'failed') {
          stopDeletePolling(filename);
        }
      } catch {
        stopDeletePolling(filename);
      }
    };
    poll();
    deletePollTimers[filename] = setInterval(poll, 1000);
  }

  async function deleteDocument(filename: string, skipConfirm = false) {
    if (isDeletingDocument(filename)) return;
    if (!skipConfirm && !confirm(`确定要删除文档 "${filename}" 吗？这将同时删除所有相关向量数据。`)) return;
    setDeleteJob(filename, {
      status: 'running', message: '正在提交删除任务...', collapsed: false,
      steps: createDeleteSteps().map(s => s.key === 'prepare' ? { ...s, percent: 1, status: 'running' as const, message: '正在提交...' } : s),
    });
    try {
      const response = await api.delete(`/documents/delete/async/${encodeURIComponent(filename)}`);
      const data = response.data;
      setDeleteJob(filename, { jobId: data.job_id, status: 'running', message: data.message || `正在删除 ${filename}` });
      startDeleteJobPolling(filename, data.job_id);
    } catch (e: unknown) {
      setDeleteJob(filename, {
        status: 'failed', message: '删除失败：' + (e as Error).message, collapsed: false,
        steps: (deleteJobs.value[filename]?.steps || createDeleteSteps()),
      });
    }
  }

  // ── Batch Operations ──
  function toggleSelectAll() {
    if (allDocsSelected.value) {
      selectedDocs.value = new Set();
    } else {
      selectedDocs.value = new Set(documents.value.map(d => d.filename));
    }
  }

  function toggleDocSelection(filename: string) {
    const next = new Set(selectedDocs.value);
    if (next.has(filename)) next.delete(filename);
    else next.add(filename);
    selectedDocs.value = next;
  }

  function batchDeleteDocuments() {
    if (selectedDocs.value.size === 0) return;
    const count = selectedDocs.value.size;
    if (!confirm(`确定要删除选中的 ${count} 个文档吗？这将同时删除所有相关向量数据。`)) return;
    const filenames = [...selectedDocs.value];
    filenames.forEach(fn => deleteDocument(fn, true));
    selectedDocs.value = new Set();
  }

  function getFileIcon(fileType: string): string {
    const map: Record<string, string> = {
      PDF: 'ph ph-file-pdf', Word: 'ph ph-file-doc', Excel: 'ph ph-file-xls', Text: 'ph ph-file-text',
    };
    return map[fileType] || 'ph ph-file';
  }

  function batchFileStatusLabel(bf: BatchFile): string {
    const map: Record<string, string> = {
      pending: '等待中', uploading: '上传中...', running: '处理中...',
      completed: '已完成', failed: '失败', cancelled: '已取消',
    };
    return map[bf.status] || bf.status;
  }

  // Cleanup on store teardown
  function cleanup() {
    stopUploadJobPolling();
    Object.keys(deletePollTimers).forEach(fn => stopDeletePolling(fn));
    Object.values(deleteRemoveTimers).forEach(clearTimeout);
    batchFiles.value.forEach(bf => {
      if (bf.xhr) { try { bf.xhr.abort(); } catch { /* ok */ } }
      if (bf.pollTimer) clearInterval(bf.pollTimer);
    });
  }

  return {
    documents, documentsLoading, selectedFile, isUploading, uploadSteps, uploadProgressCollapsed,
    activeUploadJobId, batchFiles, selectedDocs, deleteJobs,
    allDocsSelected, selectedDocsCount, batchSummary,
    loadDocuments, uploadDocument, uploadFileWithProgress,
    updateUploadStep, createUploadSteps, startUploadJobPolling, stopUploadJobPolling,
    deleteDocument, isDeletingDocument, setDeleteJob, startDeleteJobPolling,
    toggleSelectAll, toggleDocSelection, batchDeleteDocuments,
    getFileIcon, batchFileStatusLabel, cleanup,
  };
});

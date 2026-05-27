const { createApp } = Vue;

createApp({
    data() {
        return {
            // 聊天
            messages: [],
            userInput: '',
            isLoading: false,
            inputFocused: false,
            abortController: null,
            sessionId: 'session_' + Date.now(),
            MODEL_DISPLAY: 'Qwen',

            // 历史
            sessions: [],
            showHistorySidebar: false,
            activeNav: 'newChat',
            isComposing: false,

            // 认证
            token: localStorage.getItem('accessToken') || '',
            currentUser: null,
            authMode: 'login',
            authForm: { username: '', password: '', role: 'user', admin_code: '' },
            authLoading: false,

            // 文档管理
            documents: [],
            documentsLoading: false,
            selectedFile: null,
            isUploading: false,
            uploadProgress: '',
            uploadSteps: [],
            uploadProgressCollapsed: false,
            activeUploadJobId: '',
            uploadPollTimer: null,
            deleteJobs: {},
            deletePollTimers: {},
            deleteRemoveTimers: {},
            // 批量上传
            batchFiles: [],
            // 批量删除
            selectedDocs: new Set(),

            // 用户管理
            users: [],
            usersLoading: false,

            // 欢迎提示
            welcomeHints: [
                '知渊是什么？',
                '介绍一下 RAG 检索流程',
                '有哪些技术规格？',
                '支持哪些文档格式？',
            ],
        };
    },

    computed: {
        isAuthenticated() { return !!this.token && !!this.currentUser; },
        isAdmin() { return this.currentUser?.role === 'admin'; },
        allDocsSelected() {
            return this.documents.length > 0 && this.selectedDocs.size === this.documents.length;
        },
        selectedDocsCount() {
            return this.selectedDocs.size;
        },
        batchSummary() {
            if (!this.batchFiles.length) return '';
            const completed = this.batchFiles.filter(f => f.status === 'completed').length;
            const failed = this.batchFiles.filter(f => f.status === 'failed').length;
            const cancelled = this.batchFiles.filter(f => f.status === 'cancelled').length;
            const uploading = this.batchFiles.filter(f => f.status === 'uploading' || f.status === 'running').length;
            let s = `${completed}/${this.batchFiles.length} 完成`;
            if (failed) s += `，${failed} 失败`;
            if (cancelled) s += `，${cancelled} 已取消`;
            if (uploading) s += `，${uploading} 处理中`;
            return s;
        },
    },

    async mounted() {
        this.configureMarked();
        if (this.token) {
            try { await this.fetchMe(); }
            catch (_) { this.handleLogout(); }
        }
    },

    beforeUnmount() {
        this.stopUploadJobPolling();
        this.stopAllDeleteJobPolling();
        Object.values(this.deleteRemoveTimers).forEach(clearTimeout);
        this.batchFiles.forEach((bf, idx) => {
            if (bf.xhr) { try { bf.xhr.abort(); } catch (_) {} }
            this.stopBatchJobPolling(idx);
        });
    },

    methods: {
        // ========================
        //  工具方法
        // ========================
        configureMarked() {
            marked.setOptions({
                highlight: function(code, lang) {
                    const language = hljs.getLanguage(lang) ? lang : 'plaintext';
                    return hljs.highlight(code, { language }).value;
                },
                langPrefix: 'hljs language-',
                breaks: true,
                gfm: true,
            });
        },

        parseMarkdown(text) { return marked.parse(text || ''); },

        escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text || '';
            return div.innerHTML;
        },

        authHeaders(extra = {}) {
            const headers = { ...extra };
            if (this.token) headers.Authorization = `Bearer ${this.token}`;
            return headers;
        },

        async authFetch(url, options = {}) {
            const opts = { ...options };
            opts.headers = this.authHeaders(opts.headers || {});
            const response = await fetch(url, opts);
            if (response.status === 401) { this.handleLogout(); throw new Error('登录已过期'); }
            return response;
        },

        // ========================
        //  认证
        // ========================
        async fetchMe() {
            const response = await this.authFetch('/auth/me');
            if (!response.ok) throw new Error('认证失败');
            this.currentUser = await response.json();
        },

        async handleAuthSubmit() {
            if (this.authLoading) return;
            const username = this.authForm.username.trim();
            const password = this.authForm.password.trim();
            if (!username || !password) { alert('用户名和密码不能为空'); return; }

            this.authLoading = true;
            try {
                const endpoint = this.authMode === 'login' ? '/auth/login' : '/auth/register';
                const payload = { username, password };
                if (this.authMode === 'register') {
                    payload.role = this.authForm.role;
                    payload.admin_code = this.authForm.admin_code || null;
                }

                const response = await fetch(endpoint, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });

                const data = await response.json().catch(() => ({}));
                if (!response.ok) throw new Error(data.detail || '认证失败');

                this.token = data.access_token;
                this.currentUser = { username: data.username, role: data.role };
                localStorage.setItem('accessToken', this.token);
                this.authForm.password = '';
                this.authForm.admin_code = '';
                this.messages = [];
                this.sessionId = 'session_' + Date.now();
                this.activeNav = 'newChat';
            } catch (error) {
                alert(error.message);
            } finally {
                this.authLoading = false;
            }
        },

        handleLogout() {
            this.token = '';
            this.currentUser = null;
            this.messages = [];
            this.sessions = [];
            this.documents = [];
            this.activeNav = 'newChat';
            this.showHistorySidebar = false;
            localStorage.removeItem('accessToken');
        },

        // ========================
        //  输入 / 聊天
        // ========================
        handleCompositionStart() { this.isComposing = true; },
        handleCompositionEnd() { this.isComposing = false; },

        handleKeyDown(event) {
            if (event.key === 'Enter' && !event.shiftKey && !this.isComposing) {
                event.preventDefault();
                this.handleSend();
            }
        },

        handleStop() {
            if (this.abortController) this.abortController.abort();
        },

        handleHint(hint) {
            this.userInput = hint;
            this.handleSend();
        },

        async handleSend() {
            if (!this.isAuthenticated) { alert('请先登录'); return; }
            const text = this.userInput.trim();
            if (!text || this.isLoading || this.isComposing) return;

            this.messages.push({ text, isUser: true });
            this.userInput = '';
            this.$nextTick(() => { this.resetTextareaHeight(); this.scrollToBottom(); });

            this.isLoading = true;
            this.messages.push({ text: '', isUser: false, isThinking: true, ragTrace: null, ragSteps: [], webSources: null });
            const botMsgIdx = this.messages.length - 1;
            this.abortController = new AbortController();

            try {
                const response = await this.authFetch('/chat/stream', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message: text, session_id: this.sessionId }),
                    signal: this.abortController.signal,
                });
                if (!response.ok) throw new Error(`HTTP ${response.status}`);

                const reader = response.body.getReader();
                const decoder = new TextDecoder();
                let buffer = '';

                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;
                    buffer += decoder.decode(value, { stream: true });

                    let eventEndIdx;
                    while ((eventEndIdx = buffer.indexOf('\n\n')) !== -1) {
                        const eventStr = buffer.slice(0, eventEndIdx);
                        buffer = buffer.slice(eventEndIdx + 2);
                        if (!eventStr.startsWith('data: ')) continue;

                        const dataStr = eventStr.slice(6);
                        if (dataStr === '[DONE]') continue;
                        try {
                            const data = JSON.parse(dataStr);
                            const bot = this.messages[botMsgIdx];
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
                            } else if (data.type === 'error') {
                                bot.isThinking = false;
                                bot.text += `\n\n*错误：${data.content}*`;
                            }
                        } catch (e) { console.warn('SSE 解析:', e); }
                    }
                    this.$nextTick(() => this.scrollToBottom());
                }
            } catch (error) {
                const bot = this.messages[botMsgIdx];
                if (error.name === 'AbortError') {
                    bot.isThinking = false;
                    bot.text = bot.text ? bot.text + '\n\n*— 已停止 —*' : '*(已停止回答)*';
                } else {
                    bot.isThinking = false;
                    bot.text = `发生错误：${error.message}`;
                }
            } finally {
                this.isLoading = false;
                this.abortController = null;
                this.$nextTick(() => this.scrollToBottom());
            }
        },

        autoResize(event) {
            const ta = event.target;
            ta.style.height = 'auto';
            ta.style.height = ta.scrollHeight + 'px';
        },

        resetTextareaHeight() {
            if (this.$refs.textarea) this.$refs.textarea.style.height = 'auto';
        },

        scrollToBottom() {
            if (this.$refs.chatContainer) {
                this.$refs.chatContainer.scrollTop = this.$refs.chatContainer.scrollHeight;
            }
        },

        // ========================
        //  导航
        // ========================
        handleNewChat() {
            if (!this.isAuthenticated) return;
            this.messages = [];
            this.sessionId = 'session_' + Date.now();
            this.activeNav = 'newChat';
            this.showHistorySidebar = false;
        },

        handleClearChat() {
            if (confirm('确定要清空当前对话吗？')) this.messages = [];
        },

        async handleHistory() {
            if (!this.isAuthenticated) return;
            this.activeNav = 'history';
            this.showHistorySidebar = true;
            try {
                const response = await this.authFetch('/sessions');
                if (!response.ok) throw new Error('加载失败');
                const data = await response.json();
                this.sessions = data.sessions;
            } catch (error) {
                alert('加载历史记录失败：' + error.message);
            }
        },

        async loadSession(sid) {
            this.sessionId = sid;
            this.showHistorySidebar = false;
            this.activeNav = 'newChat';
            try {
                const response = await this.authFetch(`/sessions/${encodeURIComponent(sid)}`);
                if (!response.ok) throw new Error('加载失败');
                const data = await response.json();
                this.messages = data.messages.map(msg => ({
                    text: msg.content,
                    isUser: msg.type === 'human',
                    ragTrace: msg.rag_trace || null,
                    webSources: msg.web_sources || null,
                }));
                this.$nextTick(() => this.scrollToBottom());
            } catch (error) {
                alert('加载会话失败：' + error.message);
                this.messages = [];
            }
        },

        async deleteSession(sid) {
            if (!confirm(`确定要删除会话 "${sid}" 吗？`)) return;
            try {
                const response = await this.authFetch(`/sessions/${encodeURIComponent(sid)}`, { method: 'DELETE' });
                const payload = await response.json().catch(() => ({}));
                if (!response.ok) throw new Error(payload.detail || '删除失败');
                this.sessions = this.sessions.filter(s => s.session_id !== sid);
                if (this.sessionId === sid) {
                    this.messages = [];
                    this.sessionId = 'session_' + Date.now();
                    this.activeNav = 'newChat';
                }
            } catch (error) {
                alert('删除会话失败：' + error.message);
            }
        },

        // ========================
        //  知识库管理
        // ========================
        handleSettings() {
            if (!this.isAdmin) { alert('仅管理员可访问知识库管理'); return; }
            this.activeNav = 'settings';
            this.showHistorySidebar = false;
            this.loadDocuments();
        },

        handleFileDrop(event) {
            const files = event.dataTransfer?.files;
            if (!files || files.length === 0) return;
            if (files.length === 1) {
                this.selectedFile = files[0];
                this.uploadProgress = '';
                this.uploadSteps = this.createUploadSteps();
                this.uploadProgressCollapsed = false;
                this.activeUploadJobId = '';
                this.batchFiles = [];
            } else {
                this.selectedFile = null;
                this.batchFiles = Array.from(files).map(file => ({
                    file,
                    status: 'pending',
                    jobId: '',
                    message: '',
                    steps: this.createUploadSteps(),
                    collapsed: false,
                    xhr: null,
                    pollTimer: null,
                }));
                this.uploadProgress = '';
                this.uploadSteps = [];
            }
        },

        handleFileSelect(event) {
            const files = event.target.files;
            if (!files || files.length === 0) return;
            if (files.length === 1) {
                this.selectedFile = files[0];
                this.uploadProgress = '';
                this.uploadSteps = this.createUploadSteps();
                this.uploadProgressCollapsed = false;
                this.activeUploadJobId = '';
                this.batchFiles = [];
            } else {
                this.selectedFile = null;
                this.batchFiles = Array.from(files).map(file => ({
                    file,
                    status: 'pending',
                    jobId: '',
                    message: '',
                    steps: this.createUploadSteps(),
                    collapsed: false,
                    xhr: null,
                    pollTimer: null,
                }));
                this.uploadProgress = '';
                this.uploadSteps = [];
            }
        },

        // ---- 上传 ----
        createUploadSteps() {
            return [
                { key: 'upload', label: '文件上传', percent: 0, status: 'pending', message: '' },
                { key: 'cleanup', label: '清理旧版本', percent: 0, status: 'pending', message: '' },
                { key: 'parse', label: '文档解析与分块', percent: 0, status: 'pending', message: '' },
                { key: 'parent_store', label: '父级分块入库', percent: 0, status: 'pending', message: '' },
                { key: 'vector_store', label: '向量化索引', percent: 0, status: 'pending', message: '' },
            ];
        },

        updateUploadStep(key, percent, status = 'running', message = '') {
            if (!this.uploadSteps.length) this.uploadSteps = this.createUploadSteps();
            const idx = this.uploadSteps.findIndex(s => s.key === key);
            if (idx === -1) return;
            this.uploadSteps[idx] = {
                ...this.uploadSteps[idx],
                percent: Math.max(0, Math.min(100, Math.round(percent || 0))),
                status,
                message,
            };
        },

        uploadFileWithProgress(file) {
            return new Promise((resolve, reject) => {
                const xhr = new XMLHttpRequest();
                const fd = new FormData();
                fd.append('file', file);
                xhr.open('POST', '/documents/upload/async');
                const headers = this.authHeaders();
                Object.entries(headers).forEach(([k, v]) => xhr.setRequestHeader(k, v));
                xhr.upload.onprogress = (e) => {
                    if (!e.lengthComputable) return;
                    const pct = Math.round((e.loaded / e.total) * 100);
                    this.updateUploadStep('upload', pct, 'running', `已上传 ${pct}%`);
                };
                xhr.onload = () => {
                    if (xhr.status === 401) { this.handleLogout(); reject(new Error('登录已过期')); return; }
                    let data = {};
                    try { data = JSON.parse(xhr.responseText || '{}'); } catch (_) { reject(new Error('响应解析失败')); return; }
                    if (xhr.status < 200 || xhr.status >= 300) { reject(new Error(data.detail || `HTTP ${xhr.status}`)); return; }
                    this.updateUploadStep('upload', 100, 'completed', '文件已保存');
                    resolve(data);
                };
                xhr.onerror = () => reject(new Error('上传请求失败'));
                xhr.onabort = () => reject(new Error('上传已取消'));
                xhr.send(fd);
            });
        },

        syncUploadJob(job) {
            this.activeUploadJobId = job.job_id;
            this.uploadProgress = job.message || '';
            if (Array.isArray(job.steps)) {
                this.uploadSteps = job.steps.map(s => ({
                    key: s.key, label: s.label, percent: s.percent, status: s.status, message: s.message || '',
                }));
            }
            if (job.status === 'completed') this.uploadProgressCollapsed = true;
        },

        toggleUploadProgressCollapsed() { this.uploadProgressCollapsed = !this.uploadProgressCollapsed; },

        stopUploadJobPolling() {
            if (this.uploadPollTimer) { clearInterval(this.uploadPollTimer); this.uploadPollTimer = null; }
        },

        startUploadJobPolling(jobId) {
            this.stopUploadJobPolling();
            const poll = async () => {
                try {
                    const resp = await this.authFetch(`/documents/upload/jobs/${encodeURIComponent(jobId)}`);
                    if (!resp.ok) { const err = await resp.json().catch(() => ({})); throw new Error(err.detail || '获取任务状态失败'); }
                    const job = await resp.json();
                    this.syncUploadJob(job);
                    if (job.status === 'completed') {
                        this.stopUploadJobPolling();
                        this.isUploading = false;
                        this.selectedFile = null;
                        if (this.$refs.fileInput) this.$refs.fileInput.value = '';
                        await this.loadDocuments();
                    } else if (job.status === 'failed') {
                        this.stopUploadJobPolling();
                        this.isUploading = false;
                    }
                } catch (e) {
                    this.uploadProgress = '进度查询失败：' + e.message;
                    this.stopUploadJobPolling();
                    this.isUploading = false;
                }
            };
            poll();
            this.uploadPollTimer = setInterval(poll, 1000);
        },

        async uploadDocument() {
            if (!this.selectedFile) { alert('请先选择文件'); return; }
            this.isUploading = true;
            this.uploadProgress = '正在上传...';
            this.uploadSteps = this.createUploadSteps();
            this.uploadProgressCollapsed = false;
            this.updateUploadStep('upload', 0, 'running', '准备上传');
            try {
                const data = await this.uploadFileWithProgress(this.selectedFile);
                this.uploadProgress = data.message;
                this.activeUploadJobId = data.job_id;
                this.startUploadJobPolling(data.job_id);
            } catch (e) {
                this.updateUploadStep('upload', 100, 'failed', e.message);
                this.uploadProgress = '上传失败：' + e.message;
                this.isUploading = false;
            }
        },

        // ---- 删除 ----
        createDeleteSteps() {
            return [
                { key: 'prepare', label: '准备删除', percent: 0, status: 'pending', message: '' },
                { key: 'bm25', label: '同步 BM25 统计', percent: 0, status: 'pending', message: '' },
                { key: 'milvus', label: '删除向量数据', percent: 0, status: 'pending', message: '' },
                { key: 'parent_store', label: '删除父级分块', percent: 0, status: 'pending', message: '' },
            ];
        },

        isDeletingDocument(filename) {
            const j = this.deleteJobs[filename];
            return j && j.status === 'running';
        },

        isDeleteActionLocked(filename) {
            const j = this.deleteJobs[filename];
            return j && (j.status === 'running' || j.status === 'completed');
        },

        getDeleteButtonIcon(_filename) {
            const job = this.deleteJobs[_filename];
            if (job?.status === 'running') return 'fas fa-spinner fa-spin';
            if (job?.status === 'completed') return 'fas fa-check';
            return 'fas fa-trash';
        },

        setDeleteJob(filename, next) {
            this.deleteJobs = { ...this.deleteJobs, [filename]: { ...(this.deleteJobs[filename] || {}), ...next } };
        },

        syncDeleteJob(filename, job) {
            const cur = this.deleteJobs[filename] || {};
            this.setDeleteJob(filename, {
                jobId: job.job_id, status: job.status, message: job.message || '',
                collapsed: job.status === 'completed' ? true : Boolean(cur.collapsed),
                steps: Array.isArray(job.steps) ? job.steps.map(s => ({
                    key: s.key, label: s.label, percent: s.percent, status: s.status, message: s.message || '',
                })) : this.createDeleteSteps(),
            });
        },

        toggleDeleteJobCollapsed(filename) {
            const j = this.deleteJobs[filename];
            if (!j) return;
            this.setDeleteJob(filename, { collapsed: !j.collapsed });
        },

        stopDeleteJobPolling(filename) {
            const t = this.deletePollTimers[filename];
            if (!t) return;
            clearInterval(t);
            const { [filename]: _, ...rest } = this.deletePollTimers;
            this.deletePollTimers = rest;
        },

        stopAllDeleteJobPolling() {
            Object.keys(this.deletePollTimers).forEach(f => this.stopDeleteJobPolling(f));
        },

        clearDeleteRemovalTimer(filename) {
            const t = this.deleteRemoveTimers[filename];
            if (!t) return;
            clearTimeout(t);
            const { [filename]: _, ...rest } = this.deleteRemoveTimers;
            this.deleteRemoveTimers = rest;
        },

        scheduleDeletedDocumentRemoval(filename) {
            this.clearDeleteRemovalTimer(filename);
            const timer = setTimeout(async () => {
                this.documents = this.documents.filter(d => d.filename !== filename);
                const { [filename]: _j, ...jobs } = this.deleteJobs;
                const { [filename]: _t, ...timers } = this.deleteRemoveTimers;
                this.deleteJobs = jobs;
                this.deleteRemoveTimers = timers;
                await this.loadDocuments();
            }, 3000);
            this.deleteRemoveTimers = { ...this.deleteRemoveTimers, [filename]: timer };
        },

        startDeleteJobPolling(filename, jobId) {
            this.stopDeleteJobPolling(filename);
            const poll = async () => {
                try {
                    const resp = await this.authFetch(`/documents/delete/jobs/${encodeURIComponent(jobId)}`);
                    if (!resp.ok) { const err = await resp.json().catch(() => ({})); throw new Error(err.detail || '获取任务状态失败'); }
                    const job = await resp.json();
                    this.syncDeleteJob(filename, job);
                    if (job.status === 'completed') { this.stopDeleteJobPolling(filename); this.scheduleDeletedDocumentRemoval(filename); }
                    else if (job.status === 'failed') { this.stopDeleteJobPolling(filename); }
                } catch (e) {
                    this.setDeleteJob(filename, {
                        status: 'failed', message: '进度查询失败：' + e.message, collapsed: false,
                        steps: this.deleteJobs[filename]?.steps || this.createDeleteSteps(),
                    });
                    this.stopDeleteJobPolling(filename);
                }
            };
            poll();
            this.deletePollTimers = { ...this.deletePollTimers, [filename]: setInterval(poll, 1000) };
        },

        async deleteDocument(filename, skipConfirm = false) {
            if (this.isDeletingDocument(filename)) return;
            if (!skipConfirm && !confirm(`确定要删除文档 "${filename}" 吗？这将同时删除所有相关向量数据。`)) return;
            this.clearDeleteRemovalTimer(filename);
            this.setDeleteJob(filename, {
                status: 'running', message: '正在提交删除任务...', collapsed: false,
                steps: this.createDeleteSteps().map(s => s.key === 'prepare' ? { ...s, percent: 1, status: 'running', message: '正在提交...' } : s),
            });
            try {
                const resp = await this.authFetch(`/documents/delete/async/${encodeURIComponent(filename)}`, { method: 'DELETE' });
                if (!resp.ok) { const err = await resp.json().catch(() => ({})); throw new Error(err.detail || '删除失败'); }
                const data = await resp.json();
                this.setDeleteJob(filename, { jobId: data.job_id, status: 'running', message: data.message || `正在删除 ${filename}`, collapsed: false });
                this.startDeleteJobPolling(filename, data.job_id);
            } catch (e) {
                this.setDeleteJob(filename, {
                    status: 'failed', message: '删除失败：' + e.message, collapsed: false,
                    steps: this.deleteJobs[filename]?.steps || this.createDeleteSteps(),
                });
            }
        },

        mergeDocumentsWithActiveDeletes(nextDocs) {
            const merged = Array.isArray(nextDocs) ? [...nextDocs] : [];
            Object.keys(this.deleteJobs).forEach(fn => {
                const j = this.deleteJobs[fn];
                if (!j || j.status === 'failed') return;
                if (!merged.some(d => d.filename === fn)) {
                    const cur = this.documents.find(d => d.filename === fn);
                    if (cur) merged.push(cur);
                }
            });
            return merged;
        },

        async loadDocuments() {
            this.documentsLoading = true;
            try {
                const resp = await this.authFetch('/documents');
                if (!resp.ok) { const d = await resp.json().catch(() => ({})); throw new Error(d.detail || '加载失败'); }
                const data = await resp.json();
                this.documents = this.mergeDocumentsWithActiveDeletes(data.documents);
            } catch (e) {
                alert('加载文档列表失败：' + e.message);
            } finally {
                this.documentsLoading = false;
            }
        },

        // ---- 图标 ----
        getFileIcon(fileType) {
            const map = {
                PDF: 'ph ph-file-pdf',
                Word: 'ph ph-file-doc',
                Excel: 'ph ph-file-xls',
                Text: 'ph ph-file-text',
            };
            return map[fileType] || 'ph ph-file';
        },

        // ========================
        //  批量上传
        // ========================
        uploadBatch() {
            if (!this.batchFiles.length) return;
            this.isUploading = true;
            this.batchFiles.forEach((bf, idx) => {
                if (bf.status === 'pending') {
                    this.uploadSingleInBatch(idx);
                }
            });
        },

        async uploadSingleInBatch(idx) {
            const bf = this.batchFiles[idx];
            if (!bf || bf.status !== 'pending') return;

            bf.status = 'uploading';
            bf.message = '正在上传...';
            bf.steps = this.createUploadSteps();
            bf.steps[0].status = 'running';
            bf.steps[0].percent = 0;
            bf.steps[0].message = '准备上传';
            bf.collapsed = false;

            try {
                const data = await this.uploadBatchFileWithXHR(idx);
                bf.status = 'running';
                bf.jobId = data.job_id;
                bf.message = data.message || '已上传，后台处理中';
                this.startBatchJobPolling(idx, data.job_id);
            } catch (e) {
                bf.status = 'failed';
                bf.message = '上传失败: ' + e.message;
                bf.steps[0].status = 'failed';
                bf.steps[0].message = e.message;
                this.checkBatchComplete();
            }
        },

        uploadBatchFileWithXHR(idx) {
            const bf = this.batchFiles[idx];
            return new Promise((resolve, reject) => {
                const xhr = new XMLHttpRequest();
                const fd = new FormData();
                fd.append('file', bf.file);
                xhr.open('POST', '/documents/upload/async');
                const headers = this.authHeaders();
                Object.entries(headers).forEach(([k, v]) => xhr.setRequestHeader(k, v));
                xhr.upload.onprogress = (e) => {
                    if (!e.lengthComputable) return;
                    const pct = Math.round((e.loaded / e.total) * 100);
                    if (bf.steps[0]) {
                        bf.steps[0].percent = pct;
                        bf.steps[0].message = '已上传 ' + pct + '%';
                    }
                };
                xhr.onload = () => {
                    if (xhr.status === 401) { this.handleLogout(); reject(new Error('登录已过期')); return; }
                    let data = {};
                    try { data = JSON.parse(xhr.responseText || '{}'); } catch (_) { reject(new Error('响应解析失败')); return; }
                    if (xhr.status < 200 || xhr.status >= 300) { reject(new Error(data.detail || 'HTTP ' + xhr.status)); return; }
                    if (bf.steps[0]) {
                        bf.steps[0].percent = 100;
                        bf.steps[0].status = 'completed';
                        bf.steps[0].message = '文件已保存';
                    }
                    resolve(data);
                };
                xhr.onerror = () => reject(new Error('上传请求失败'));
                xhr.onabort = () => reject(new Error('上传已取消'));
                xhr.send(fd);
                bf.xhr = xhr;
            });
        },

        startBatchJobPolling(idx, jobId) {
            const bf = this.batchFiles[idx];
            if (!bf) return;
            this.stopBatchJobPolling(idx);
            const poll = async () => {
                try {
                    const resp = await this.authFetch('/documents/upload/jobs/' + encodeURIComponent(jobId));
                    if (!resp.ok) { const err = await resp.json().catch(() => ({})); throw new Error(err.detail || '获取任务状态失败'); }
                    const job = await resp.json();
                    if (Array.isArray(job.steps)) {
                        bf.steps = job.steps.map(s => ({
                            key: s.key, label: s.label, percent: s.percent, status: s.status, message: s.message || '',
                        }));
                    }
                    bf.message = job.message || '';
                    if (job.status === 'completed') {
                        bf.status = 'completed';
                        bf.collapsed = true;
                        this.stopBatchJobPolling(idx);
                        this.checkBatchComplete();
                    } else if (job.status === 'failed') {
                        bf.status = 'failed';
                        this.stopBatchJobPolling(idx);
                        this.checkBatchComplete();
                    } else if (job.status === 'cancelled') {
                        bf.status = 'cancelled';
                        this.stopBatchJobPolling(idx);
                        this.checkBatchComplete();
                    }
                } catch (_) {
                    bf.status = 'failed';
                    bf.message = '进度查询失败';
                    this.stopBatchJobPolling(idx);
                    this.checkBatchComplete();
                }
            };
            poll();
            bf.pollTimer = setInterval(poll, 1000);
        },

        stopBatchJobPolling(idx) {
            const bf = this.batchFiles[idx];
            if (bf && bf.pollTimer) { clearInterval(bf.pollTimer); bf.pollTimer = null; }
        },

        cancelBatchUpload(idx) {
            const bf = this.batchFiles[idx];
            if (!bf) return;
            if (bf.xhr) { bf.xhr.abort(); bf.xhr = null; }
            if (bf.jobId) {
                this.authFetch('/documents/upload/jobs/' + encodeURIComponent(bf.jobId) + '/cancel', { method: 'POST' })
                    .catch(() => {});
            }
            this.stopBatchJobPolling(idx);
            bf.status = 'cancelled';
            bf.message = '已取消';
            this.checkBatchComplete();
        },

        checkBatchComplete() {
            const allDone = this.batchFiles.every(f =>
                ['completed', 'failed', 'cancelled'].includes(f.status)
            );
            if (allDone) {
                this.isUploading = false;
                if (this.$refs.fileInput) this.$refs.fileInput.value = '';
                this.loadDocuments();
            }
        },

        batchFileStatusLabel(bf) {
            const map = {
                pending: '等待中',
                uploading: '上传中...',
                running: '处理中...',
                completed: '已完成',
                failed: '失败',
                cancelled: '已取消',
            };
            return map[bf.status] || bf.status;
        },

        // ========================
        //  批量删除
        // ========================
        toggleSelectAll() {
            if (this.allDocsSelected) {
                this.selectedDocs = new Set();
            } else {
                this.selectedDocs = new Set(this.documents.map(d => d.filename));
            }
        },

        toggleDocSelection(filename) {
            const next = new Set(this.selectedDocs);
            if (next.has(filename)) {
                next.delete(filename);
            } else {
                next.add(filename);
            }
            this.selectedDocs = next;
        },

        batchDeleteDocuments() {
            if (this.selectedDocs.size === 0) return;
            const count = this.selectedDocs.size;
            if (!confirm('确定要删除选中的 ' + count + ' 个文档吗？这将同时删除所有相关向量数据。')) return;

            const filenames = [...this.selectedDocs];

            filenames.forEach(filename => {
                this.deleteDocument(filename, true);
            });

            this.selectedDocs = new Set();
        },

        // ========================
        //  用户管理
        // ========================
        handleUserManagement() {
            if (!this.isAdmin) { alert('仅管理员可访问用户管理'); return; }
            this.activeNav = 'users';
            this.showHistorySidebar = false;
            this.fetchUsers();
        },

        async fetchUsers() {
            this.usersLoading = true;
            try {
                const resp = await this.authFetch('/users');
                if (!resp.ok) { const d = await resp.json().catch(() => ({})); throw new Error(d.detail || '加载失败'); }
                const data = await resp.json();
                this.users = data.users || [];
            } catch (e) {
                alert('加载用户列表失败：' + e.message);
            } finally {
                this.usersLoading = false;
            }
        },

        async deleteUser(username) {
            if (!confirm('确定要删除用户 "' + username + '" 吗？此操作不可撤销，将同时删除该用户的所有聊天记录。')) return;
            try {
                const resp = await this.authFetch('/users/' + encodeURIComponent(username), { method: 'DELETE' });
                if (!resp.ok) { const d = await resp.json().catch(() => ({})); throw new Error(d.detail || '删除失败'); }
                this.users = this.users.filter(u => u.username !== username);
            } catch (e) {
                alert('删除用户失败：' + e.message);
            }
        },

        async toggleUserRole(user) {
            const newRole = user.role === 'admin' ? 'user' : 'admin';
            const actionLabel = newRole === 'admin' ? '提升为管理员' : '降级为普通用户';
            if (!confirm('确定要将用户 "' + user.username + '" ' + actionLabel + '吗？')) return;
            try {
                const resp = await this.authFetch('/users/' + encodeURIComponent(user.username) + '/role', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ role: newRole }),
                });
                if (!resp.ok) { const d = await resp.json().catch(() => ({})); throw new Error(d.detail || '操作失败'); }
                user.role = newRole;
            } catch (e) {
                alert('修改角色失败：' + e.message);
            }
        },

        formatUserDate(isoStr) {
            if (!isoStr) return '--';
            try {
                return new Date(isoStr).toLocaleString('zh-CN');
            } catch (_) {
                return isoStr;
            }
        },
    },

    watch: {
        messages: {
            handler() { this.$nextTick(() => this.scrollToBottom()); },
            deep: true,
        },
    },
}).mount('#app');

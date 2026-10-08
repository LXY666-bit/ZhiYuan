<template>
  <section class="research-workbench">
    <header class="research-header">
      <div>
        <span class="panel-eyebrow">Research workbench</span>
        <h1>深度研搜</h1>
        <p>先确认研究计划，再搜集证据、核验结论并交付可审阅的报告。</p>
      </div>
      <button class="primary" type="button" @click="showCreate = !showCreate">
        {{ showCreate ? '收起' : '新建研究' }}
      </button>
    </header>

    <form v-if="showCreate" class="research-card create-form" @submit.prevent="createProject">
      <div class="create-heading">
        <span class="card-eyebrow">NEW RESEARCH</span>
        <strong>创建研究草稿</strong>
        <small>先确定目标和资料来源，附件可在审批前随时补充。</small>
      </div>
      <label>标题<input v-model.trim="form.title" maxlength="200" required /></label>
      <label>研究目标<textarea v-model.trim="form.objective" rows="4" required /></label>
      <label
        >模式
        <select v-model="form.mode">
          <option value="quick">Quick · 快速概览</option>
          <option value="standard">Standard · 核验与定向补研</option>
          <option value="deep">Deep · 更多证据与研究维度</option>
        </select>
      </label>
      <p class="research-muted">{{ modeDescription(form.mode) }}</p>
      <div class="checkboxes">
        <label><input v-model="form.sources" type="checkbox" value="knowledge_base" />知识库</label>
        <label><input v-model="form.sources" type="checkbox" value="web" />Web</label>
        <label><input v-model="form.sources" type="checkbox" value="attachments" />附件</label>
        <label
          ><input v-model="form.output_formats" type="checkbox" value="pdf" />同时生成 PDF</label
        >
      </div>
      <button
        class="primary create-submit"
        type="submit"
        :disabled="store.busy || !form.sources.length"
      >
        创建
      </button>
    </form>

    <p v-if="store.error" class="research-error" role="alert">{{ store.error }}</p>
    <div class="research-grid">
      <aside class="research-card project-list">
        <div class="project-list-heading">
          <span>研究项目</span>
          <small>{{ store.projects.length }} 个项目</small>
        </div>
        <button
          v-for="project in store.projects"
          :key="project.id"
          type="button"
          :class="{ active: project.id === store.selectedId }"
          @click="store.select(project.id)"
        >
          <strong>{{ project.title }}</strong>
          <small>{{ modeLabel(project.mode) }} · {{ statusLabel(project) }}</small>
        </button>
        <p v-if="!store.projects.length && !store.loading">还没有研究项目。</p>
      </aside>

      <main v-if="store.selected" class="research-detail">
        <article class="research-card project-overview">
          <div class="project-overview-header">
            <div class="project-intro">
              <span class="card-eyebrow">{{ modeLabel(store.selected.mode) }} RESEARCH</span>
              <h2>{{ store.selected.title }}</h2>
              <p>{{ store.selected.objective }}</p>
            </div>
            <span class="status-chip">{{ statusLabel(store.selected) }}</span>
          </div>
          <div class="actions primary-actions" v-if="store.selected.lifecycle_status !== 'frozen'">
            <button
              type="button"
              class="primary"
              :disabled="store.busy || activePlanJob"
              @click="store.generatePlan"
            >
              生成研究计划
            </button>
            <button
              v-if="activePlanJob"
              type="button"
              class="secondary-button"
              @click="store.cancelPlan"
            >
              取消计划任务
            </button>
            <button
              v-if="store.plan"
              type="button"
              class="secondary-button"
              :disabled="store.busy || planDirty || activePlanJob"
              @click="approvePlan"
            >
              批准并开始研究
            </button>
            <label class="upload-button">
              添加附件
              <input
                type="file"
                accept=".pdf,.docx,.doc,.xlsx,.xls,.html,.htm"
                @change="uploadAttachment"
              />
            </label>
          </div>
          <div class="actions secondary-actions">
            <button type="button" class="text-button" @click="store.cloneSelected">复制项目</button>
            <button
              v-if="runState && runState.terminal"
              type="button"
              :disabled="store.busy"
              class="text-button"
              @click="store.rerun"
            >
              重新研究
            </button>
            <button
              v-if="runState && !runState.terminal"
              type="button"
              class="text-button"
              @click="runs.cancel(runState.runId)"
            >
              取消运行
            </button>
            <button type="button" class="danger" @click="deleteProject">删除项目</button>
          </div>
          <p v-if="store.planJob" class="job-state">
            Plan Job：{{ store.planJob.status }} · 尝试 {{ store.planJob.attempts }}
          </p>
        </article>

        <article v-if="store.plan" class="research-card plan-card">
          <div class="card-heading">
            <div>
              <span class="card-eyebrow">RESEARCH PLAN</span>
              <h3>
                研究计划 <span>v{{ store.plan.version }}</span>
              </h3>
            </div>
            <span class="step-count">{{ editableSteps.length }} 个研究步骤</span>
          </div>
          <ol class="plan-editor">
            <li v-for="(step, index) in editableSteps" :key="step.step_key">
              <span class="step-number">{{ String(index + 1).padStart(2, '0') }}</span>
              <div class="step-fields">
                <label
                  >步骤标题<input
                    v-model.trim="step.title"
                    aria-label="步骤标题"
                    :disabled="
                      store.selected.lifecycle_status === 'frozen' || store.busy || activePlanJob
                    "
                /></label>
                <label
                  >研究问题<textarea
                    v-model.trim="step.question"
                    rows="2"
                    aria-label="研究问题"
                    :disabled="
                      store.selected.lifecycle_status === 'frozen' || store.busy || activePlanJob
                    "
                  />
                </label>
                <div class="source-tags" aria-label="资料来源">
                  <span v-for="source in step.sources" :key="source">{{
                    sourceLabel(source)
                  }}</span>
                </div>
              </div>
            </li>
          </ol>
          <p v-if="planDirty" class="research-muted" role="status">
            计划有未保存修改，请保存新版本后再批准研究。
          </p>
          <button
            v-if="store.selected.lifecycle_status !== 'frozen'"
            type="button"
            class="primary save-plan-button"
            :disabled="store.busy"
            @click="savePlan"
          >
            保存为新计划版本
          </button>
        </article>

        <article v-if="store.attachments.length" class="research-card attachment-card">
          <div class="card-heading">
            <div>
              <span class="card-eyebrow">PROJECT MATERIALS</span>
              <h3>研究附件</h3>
            </div>
            <span class="step-count">{{ store.attachments.length }} 个文件</span>
          </div>
          <div v-for="attachment in store.attachments" :key="String(attachment.id)" class="row">
            <span class="attachment-name">{{ attachment.filename }}</span>
            <span class="attachment-status">{{ attachmentStatusLabel(attachment.status) }}</span>
            <div v-if="store.selected.lifecycle_status !== 'frozen'" class="row-actions">
              <button
                v-if="attachment.status === 'failed'"
                type="button"
                @click="store.retryAttachment(String(attachment.id))"
              >
                重试
              </button>
              <button type="button" @click="store.deleteAttachment(String(attachment.id))">
                删除
              </button>
            </div>
          </div>
        </article>

        <article v-if="runState" class="research-card run-card">
          <div class="detail-heading">
            <div>
              <span class="card-eyebrow">LIVE RESEARCH</span>
              <h3>研究进度</h3>
            </div>
            <span class="status-chip">{{ runStatusLabel(runState.status) }}</span>
          </div>
          <p v-if="runState.hasGap">事件流出现缺口，正在等待历史事件补齐。</p>
          <div class="run-phase" :class="`is-${runState.status}`">
            <span class="run-phase-dot" aria-hidden="true"></span>
            <div>
              <strong>{{ runPhase.title }}</strong>
              <p>{{ runPhase.detail }}</p>
            </div>
          </div>
          <div class="metric-row run-metrics" aria-label="本次研究用量">
            <span
              ><small>运行耗时</small><b>{{ formatDuration(runMetrics.elapsedMs) }}</b></span
            >
            <span
              ><small>输入 / 输出 Token</small
              ><b
                >{{ formatTokens(runMetrics.inputTokens) }} /
                {{ formatTokens(runMetrics.outputTokens) }}</b
              ></span
            >
            <span
              ><small>模型调用</small><b>{{ runMetrics.modelCalls }}</b></span
            >
            <span
              ><small>已采纳证据</small><b>{{ store.evidence.length }}</b></span
            >
            <span
              ><small>已检查核心结论</small><b>{{ store.claims.length }}</b></span
            >
            <span
              ><small>已完成章节</small
              ><b>{{ completedSectionCount }} / {{ executionSteps.length }}</b></span
            >
          </div>
          <p
            v-if="isRunActive && store.metrics?.run_budget_seconds"
            class="research-muted run-budget-note"
          >
            本次时间预算：{{ formatDuration(store.metrics.run_budget_seconds * 1000) }}。 已保存
            {{ store.sections.length }} 个章节，可提前阅读；超时会保留结果并标明缺口。
          </p>
          <ol v-if="executionSteps.length" class="run-steps" aria-label="研究步骤执行情况">
            <li
              v-for="step in executionSteps"
              :key="step.step_key"
              :class="[`is-${step.status}`, { selected: selectedStepKey === step.step_key }]"
            >
              <button
                type="button"
                class="run-step-trigger"
                :aria-expanded="selectedStepKey === step.step_key"
                :aria-controls="`step-evidence-${step.step_key}`"
                @click="toggleStepEvidence(step.step_key)"
              >
                <span class="run-step-marker" aria-hidden="true">{{ step.position }}</span>
                <span class="run-step-copy">
                  <span>
                    <strong>{{ step.title }}</strong>
                    <em>{{
                      step.status === 'running' && step.phase
                        ? phaseLabel(step.phase)
                        : stepStatusLabel(step.status)
                    }}</em>
                  </span>
                  <span class="run-step-question">{{ step.question }}</span>
                  <small>
                    {{ step.evidenceCount }} 条证据 · 点击查看
                    <template v-if="step.durationMs !== null">
                      · {{ formatDuration(step.durationMs) }}</template
                    >
                  </small>
                </span>
              </button>
            </li>
          </ol>
          <section
            v-if="selectedExecutionStep"
            :id="`step-evidence-${selectedExecutionStep.step_key}`"
            class="step-evidence-panel"
            aria-live="polite"
          >
            <div class="step-evidence-heading">
              <div>
                <span class="card-eyebrow">STEP EVIDENCE</span>
                <strong>{{ selectedExecutionStep.title }}</strong>
              </div>
              <span>{{ selectedStepEvidence.length }} 条已关联证据</span>
            </div>
            <p v-if="selectedSourceStats.length" class="research-muted">
              <template v-for="(item, index) in selectedSourceStats" :key="item.source">
                <span v-if="index"> · </span>{{ evidenceSourceLabel(item.source) }}：候选
                {{ item.stats.candidate_count }}，保留 {{ item.stats.evidence_count }}，过滤
                {{ item.stats.filtered_count }}，错误 {{ item.stats.error_count }}
              </template>
            </p>
            <p v-if="!selectedStepEvidence.length" class="research-muted">
              该步骤尚未保存可展示的证据；若本步骤已降级，请查看下方提示并在修复来源后重新研究。
            </p>
            <ol v-else class="step-evidence-list">
              <li v-for="evidence in selectedStepEvidence" :key="String(evidence.id)">
                <span class="evidence-citation">[{{ evidence.citation }}]</span>
                <div>
                  <strong>{{ evidence.title }}</strong>
                  <p>{{ evidenceExcerpt(evidence) }}</p>
                  <small>
                    {{ evidenceSourceLabel(evidence.source_kind) }}
                    <template v-if="evidence.domain"> · {{ evidence.domain }}</template>
                    <template v-if="evidence.quality_score !== undefined">
                      · 质量 {{ formatQuality(evidence.quality_score) }}</template
                    >
                  </small>
                </div>
              </li>
            </ol>
          </section>
          <p v-else class="research-muted">Run 已创建，正在准备研究步骤。</p>
          <details v-if="runState.warnings.length" class="run-warnings">
            <summary>查看 {{ runState.warnings.length }} 条降级提示</summary>
            <p
              v-for="(warning, index) in runState.warnings"
              :key="`${warning.code}-${warning.stage}-${index}`"
            >
              {{ warning.message }}
            </p>
          </details>
        </article>

        <article v-if="store.sections.length" class="research-card content-card">
          <div class="card-heading">
            <h3>章节</h3>
            <span class="step-count">{{ store.sections.length }} 节</span>
          </div>
          <details v-for="section in store.sections" :key="String(section.id)">
            <summary>{{ section.title }} · {{ section.status }}</summary>
            <!-- parseMarkdown sanitizes model-authored Markdown before v-html rendering. -->
            <div
              class="research-markdown"
              @click="openCitation"
              v-html="sectionMarkdown(section)"
            ></div>
          </details>
        </article>

        <article v-if="store.claims.length" class="research-card content-card claim-card">
          <div class="card-heading">
            <h3>结论核验</h3>
            <span class="step-count">{{ unresolvedClaimCount }} 项需审阅</span>
          </div>
          <details v-for="claim in store.claims" :key="String(claim.id)">
            <summary>{{ claimVerdictLabel(claim.verdict) }} · {{ claim.text }}</summary>
            <p>{{ claim.reason }}</p>
            <small class="research-muted">每章核验核心结论；其他事实仍需结合引用审阅。</small>
          </details>
        </article>

        <article
          v-if="selectedCitation"
          ref="citationPanelRef"
          tabindex="-1"
          class="research-card citation-detail"
          aria-label="引用证据详情"
        >
          <div class="card-heading">
            <h3>[{{ selectedCitation.citation }}] {{ selectedCitation.title }}</h3>
            <button type="button" @click="closeCitation">关闭证据</button>
          </div>
          <p class="research-muted">{{ evidenceSourceLabel(selectedCitation.source_kind) }}</p>
          <p class="citation-content">{{ selectedCitation.content }}</p>
          <a
            v-if="citationSourceUrl"
            :href="citationSourceUrl"
            target="_blank"
            rel="noopener noreferrer"
            >打开原始来源</a
          >
        </article>

        <article v-if="store.artifacts.length" class="research-card content-card">
          <div class="card-heading">
            <h3>交付物</h3>
            <span class="step-count">{{ store.artifacts.length }} 项</span>
          </div>
          <div v-for="artifact in store.artifacts" :key="String(artifact.id)" class="artifact-row">
            <button type="button" class="artifact-link" @click="downloadArtifact(artifact)">
              {{ artifact.filename }} · {{ artifact.state }} v{{ artifact.version }}
            </button>
            <button
              v-if="artifact.media_type === 'text/markdown' && artifact.state === 'final'"
              type="button"
              @click="openReport(artifact)"
            >
              阅读报告
            </button>
            <button
              v-if="artifact.media_type === 'text/markdown' && artifact.state === 'final'"
              type="button"
              @click="openMarkdownEditor(artifact)"
            >
              编辑
            </button>
            <button
              type="button"
              class="danger"
              :disabled="store.busy"
              @click="deleteArtifact(artifact)"
            >
              删除
            </button>
          </div>
          <div v-if="editingMarkdown" class="markdown-editor">
            <div class="markdown-editor-panels">
              <label class="markdown-source"
                >Markdown 源码
                <textarea v-model="markdownDraft" rows="18" aria-label="Markdown 报告" />
              </label>
              <section class="markdown-preview" aria-label="报告预览">
                <div class="markdown-preview-heading">
                  <span>报告预览</span>
                  <button
                    ref="previewExpandButtonRef"
                    type="button"
                    class="preview-expand-button"
                    aria-label="放大报告预览"
                    @click="openExpandedPreview"
                  >
                    <i class="fa-solid fa-expand" aria-hidden="true"></i>
                    放大预览
                  </button>
                </div>
                <!-- markdownPreview is sanitized by the shared Markdown renderer. -->
                <div class="research-markdown" @click="openCitation" v-html="markdownPreview"></div>
              </section>
            </div>
            <div class="actions">
              <button type="button" @click="closeMarkdownEditor">取消</button>
              <button type="button" class="primary" :disabled="store.busy" @click="saveMarkdown">
                保存新版本并重建 PDF
              </button>
            </div>
          </div>
        </article>
      </main>
      <main v-else class="research-card empty-detail">选择一个研究项目开始。</main>
    </div>

    <Teleport to="body">
      <div
        v-if="previewExpanded"
        class="report-preview-backdrop"
        role="presentation"
        @click.self="closeExpandedPreview"
      >
        <section
          ref="expandedPreviewDialogRef"
          class="report-preview-dialog"
          role="dialog"
          aria-modal="true"
          aria-labelledby="report-preview-title"
          tabindex="-1"
          @keydown.esc.prevent="closeExpandedPreview"
        >
          <header class="report-preview-header">
            <div>
              <span class="card-eyebrow">MARKDOWN REPORT</span>
              <h2 id="report-preview-title">报告预览</h2>
              <p>
                {{
                  readingArtifact
                    ? '正在阅读已保存的报告版本，点击引用可查看证据。'
                    : '导出 PDF 会先保存当前内容为新版本，确保交付物可以追溯。'
                }}
              </p>
            </div>
            <div class="report-preview-actions">
              <button
                v-if="!readingArtifact"
                type="button"
                class="primary report-preview-export"
                :disabled="store.busy"
                @click="exportPdf"
              >
                <i class="fa-solid fa-file-pdf" aria-hidden="true"></i>
                {{ store.busy ? '正在生成…' : '导出 PDF' }}
              </button>
              <button
                v-else
                type="button"
                class="primary"
                @click="downloadArtifact(readingArtifact)"
              >
                下载报告
              </button>
              <button
                type="button"
                class="report-preview-close"
                aria-label="关闭报告预览"
                @click="closeExpandedPreview"
              >
                <i class="fa-solid fa-xmark" aria-hidden="true"></i>
              </button>
            </div>
          </header>
          <!-- markdownPreview is sanitized by the shared Markdown renderer. -->
          <div class="report-preview-content">
            <div class="research-markdown" @click="openCitation" v-html="markdownPreview"></div>
          </div>
        </section>
      </div>
    </Teleport>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue';
import { useResearchStore } from '@/stores/research';
import { useRunsStore } from '@/stores/runs';
import type {
  ResearchMode,
  ResearchPlanStepV1,
  ResearchProjectV1,
  ResearchSource,
} from '@/types/generated/research-api-v1';
import { fetchArtifact } from '@/artifacts/artifactClient';
import type { ResearchStepResource } from '@/research/researchClient';
import { renderResearchMarkdown } from '@/research/reportMarkdown';

const store = useResearchStore();
const runs = useRunsStore();
const showCreate = ref(false);
const editableSteps = ref<ResearchPlanStepV1[]>([]);
const editingMarkdown = ref(false);
const markdownDraft = ref('');
const readingArtifact = ref<Record<string, unknown> | null>(null);
const previewExpanded = ref(false);
const previewExpandButtonRef = ref<HTMLButtonElement | null>(null);
const expandedPreviewDialogRef = ref<HTMLElement | null>(null);
const selectedStepKey = ref<string | null>(null);
const selectedCitationId = ref<string | null>(null);
const citationPanelRef = ref<HTMLElement | null>(null);
let citationTrigger: HTMLElement | null = null;
let citationWasExpanded = false;
const displayNow = ref(Date.now());
let elapsedTimer: ReturnType<typeof setInterval> | null = null;
const citationIds = computed(() => new Set(store.evidence.map((item) => String(item.citation))));
const markdownPreview = computed(() =>
  renderResearchMarkdown(markdownDraft.value, citationIds.value)
);
const selectedCitation = computed(
  () => store.evidence.find((item) => item.citation === selectedCitationId.value) || null
);
const citationSourceUrl = computed(() => {
  try {
    const url = new URL(String(selectedCitation.value?.source_uri || ''));
    return ['https:', 'http:'].includes(url.protocol) ? url.href : null;
  } catch {
    return null;
  }
});
const unresolvedClaimCount = computed(
  () => store.claims.filter((item) => item.verdict !== 'supported').length
);
const planDirty = computed(
  () =>
    Boolean(store.plan) && JSON.stringify(editableSteps.value) !== JSON.stringify(store.plan?.steps)
);
const form = reactive({
  title: '',
  objective: '',
  mode: 'quick' as ResearchMode,
  sources: ['knowledge_base'] as ResearchSource[],
  output_formats: ['markdown'] as Array<'markdown' | 'pdf'>,
});
const activePlanJob = computed(() =>
  Boolean(store.planJob && !['completed', 'failed', 'cancelled'].includes(store.planJob.status))
);
const runState = computed(() =>
  store.selected?.latest_run_id ? runs.byId[store.selected.latest_run_id] || null : null
);
const executionSteps = computed(() =>
  (store.plan?.steps || []).map((planStep, index) => {
    const runtimeStep = store.steps.find((step) => step.step_key === planStep.step_key);
    const persistedEvidenceIds = runtimeStep?.evidence_ids || [];
    return {
      ...planStep,
      position: runtimeStep?.position || index + 1,
      status: runtimeStep?.status || 'pending',
      phase: runtimeStep?.phase,
      evidenceCount: runtimeStep?.evidence_count || 0,
      evidenceIds: persistedEvidenceIds.length
        ? persistedEvidenceIds
        : sectionEvidenceIds(planStep.step_key),
      sourceStats: runtimeStep?.source_stats || {},
      durationMs: stepDuration(runtimeStep),
    };
  })
);
const selectedExecutionStep = computed(
  () => executionSteps.value.find((step) => step.step_key === selectedStepKey.value) || null
);
const selectedSourceStats = computed(() =>
  Object.entries(selectedExecutionStep.value?.sourceStats || {}).map(([source, stats]) => ({
    source,
    stats,
  }))
);
const selectedStepEvidence = computed(() => {
  const ids = new Set(selectedExecutionStep.value?.evidenceIds || []);
  return store.evidence.filter((evidence) => ids.has(String(evidence.id)));
});
const completedSectionCount = computed(
  () =>
    store.sections.filter((section) => ['completed', 'degraded'].includes(String(section.status)))
      .length
);
const degradedSectionCount = computed(
  () => store.sections.filter((section) => section.status === 'degraded').length
);
const isRunActive = computed(() =>
  Boolean(
    runState.value &&
    ['creating', 'queued', 'pending', 'running', 'cancelling'].includes(runState.value.status)
  )
);
const liveElapsedMs = computed(() => {
  const state = runState.value;
  if (!state?.activeStartedAt || !isRunActive.value) return state?.activeDurationMs || 0;
  const startedAt = Date.parse(state.activeStartedAt);
  if (!Number.isFinite(startedAt)) return state.activeDurationMs;
  return state.activeDurationMs + Math.max(displayNow.value - startedAt, 0);
});
const runMetrics = computed(() => {
  const usage = runState.value?.usage || {};
  const metrics = store.metrics;
  return {
    elapsedMs: Math.max(metrics?.elapsed_ms || 0, liveElapsedMs.value),
    inputTokens: Number(usage.input_tokens ?? metrics?.input_tokens ?? 0),
    outputTokens: Number(usage.output_tokens ?? metrics?.output_tokens ?? 0),
    modelCalls: metrics?.model_calls || 0,
  };
});
const runPhase = computed(() => {
  if (!runState.value) return { title: '等待运行', detail: '批准研究计划后开始执行。' };
  if (runState.value.status === 'completed') {
    const degraded = degradedSectionCount.value > 0 || runState.value.warnings.length > 0;
    return {
      title: degraded ? '研究已交付，部分内容降级' : '研究已交付',
      detail: `报告已保存；${degradedSectionCount.value} 个章节降级，${unresolvedClaimCount.value} 项核心结论存在冲突或尚未可靠核验。交付完成不代表全部事实已验证，请结合引用和降级提示审阅。`,
    };
  }
  if (runState.value.status === 'failed')
    return { title: '研究执行失败', detail: '可查看降级提示或重新研究。' };
  if (runState.value.status === 'cancelled')
    return { title: '研究已取消', detail: '已保留当前已写入的研究资料。' };
  const running = executionSteps.value.find((step) => step.status === 'running');
  if (running)
    return {
      title: `正在研究：${running.title}`,
      detail: running.phase
        ? phaseLabel(running.phase)
        : '检索、证据整理和章节写作会按步骤持续更新。',
    };
  if (store.sections.length)
    return { title: '正在综合研究结论', detail: '正在协调章节之间的发现、冲突和待验证问题。' };
  return { title: '正在准备研究', detail: '正在加载冻结的计划和资料范围。' };
});
const statusLabel = (project: ResearchProjectV1) =>
  runStatusLabel(project.run_status || project.lifecycle_status);
const modeLabel = (mode: ResearchMode) => mode.toUpperCase();
const modeDescription = (mode: ResearchMode) =>
  ({
    quick: '2–3 个研究步骤，适合快速了解；不追加补研，资源消耗较低。',
    standard: '3–5 个研究步骤，按具体证据缺口补研，并检查和修订章节。',
    deep: '4–6 个研究步骤，保留更多证据，按需修订；已完成章节可提前阅读。',
  })[mode];
const verdictLabels: Record<string, string> = {
  supported: '核心结论有支持',
  unsupported: '缺少证据支持',
  conflicting: '存在冲突证据',
  insufficient: '尚未可靠核验',
};
const claimVerdictLabel = (value: unknown) => verdictLabels[String(value)] || '待审阅';
const phaseLabel = (phase: string) =>
  (
    ({
      retrieving: '正在搜集证据',
      writing: '正在撰写章节',
      verifying: '正在核验结论',
      completed: '已完成',
    }) as Record<string, string>
  )[phase] || '进行中';
const sourceLabel = (source: ResearchSource) =>
  ({ knowledge_base: '知识库', web: 'Web', attachments: '附件' })[source];
const runStatusLabel = (status: string) =>
  (
    ({
      draft: '草稿',
      awaiting_approval: '等待批准',
      frozen: '已冻结',
      pending: '等待执行',
      running: '研究进行中',
      cancelling: '正在取消',
      cancelled: '已取消',
      succeeded: '已完成',
      completed: '已完成',
      failed: '执行失败',
      interrupted: '已中断',
    }) as Record<string, string>
  )[status] || status;
const attachmentStatusLabel = (status: unknown) =>
  (
    ({
      pending: '等待处理',
      indexing: '正在索引',
      indexed: '已索引',
      failed: '索引失败',
    }) as Record<string, string>
  )[String(status)] || String(status);
const stepStatusLabel = (status: string) =>
  (
    ({
      pending: '等待执行',
      running: '进行中',
      completed: '已完成',
      degraded: '已降级交付',
      failed: '执行失败',
    }) as Record<string, string>
  )[status] || status;
function stepDuration(step: ResearchStepResource | undefined): number | null {
  if (!step?.started_at || !step.finished_at) return null;
  const started = Date.parse(step.started_at);
  const finished = Date.parse(step.finished_at);
  return Number.isFinite(started) && Number.isFinite(finished) && finished >= started
    ? finished - started
    : null;
}
function sectionEvidenceIds(stepKey: string): string[] {
  const section = store.sections.find((item) => String(item.section_key) === stepKey);
  const evidenceIds = section?.evidence_ids;
  return Array.isArray(evidenceIds)
    ? evidenceIds.filter((value): value is string => typeof value === 'string')
    : [];
}
function toggleStepEvidence(stepKey: string) {
  selectedStepKey.value = selectedStepKey.value === stepKey ? null : stepKey;
}
function evidenceExcerpt(evidence: Record<string, unknown>): string {
  const content = String(evidence.content || '')
    .replace(/\s+/g, ' ')
    .trim();
  return content.length > 220 ? `${content.slice(0, 220)}…` : content;
}
function evidenceSourceLabel(value: unknown): string {
  return (
    ({ knowledge_base: '知识库', web: 'Web', attachments: '附件' } as Record<string, string>)[
      String(value)
    ] || '来源'
  );
}
function formatQuality(value: unknown): string {
  const score = Number(value);
  return Number.isFinite(score) ? score.toFixed(2) : '—';
}
function formatDuration(value: number): string {
  const seconds = Math.max(0, Math.round(value / 1000));
  const minutes = Math.floor(seconds / 60);
  return minutes ? `${minutes} 分 ${String(seconds % 60).padStart(2, '0')} 秒` : `${seconds} 秒`;
}
function formatTokens(value: number): string {
  return new Intl.NumberFormat('zh-CN', { notation: 'compact', maximumFractionDigits: 1 }).format(
    Math.max(0, value)
  );
}
function sectionMarkdown(section: Record<string, unknown>): string {
  return renderResearchMarkdown(
    typeof section.content_markdown === 'string' ? section.content_markdown : '',
    citationIds.value
  );
}
async function approvePlan() {
  if (planDirty.value || activePlanJob.value || store.busy) return;
  await store.approve();
}
async function openCitation(event: MouseEvent) {
  const trigger = (event.target as HTMLElement).closest<HTMLElement>('[data-citation]');
  if (!trigger || !citationIds.value.has(trigger.dataset.citation || '')) return;
  selectedCitationId.value = trigger.dataset.citation || null;
  citationTrigger = trigger;
  citationWasExpanded = previewExpanded.value;
  previewExpanded.value = false;
  await nextTick();
  citationPanelRef.value?.focus();
  citationPanelRef.value?.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' });
}
async function closeCitation() {
  const citation = selectedCitationId.value;
  selectedCitationId.value = null;
  if (citationWasExpanded) {
    previewExpanded.value = true;
    await nextTick();
    expandedPreviewDialogRef.value
      ?.querySelector<HTMLElement>(`[data-citation="${citation}"]`)
      ?.focus();
  } else citationTrigger?.focus();
  citationTrigger = null;
}
watch(
  () => store.selectedId,
  () => {
    selectedCitationId.value = null;
    selectedStepKey.value = null;
    editingMarkdown.value = false;
    previewExpanded.value = false;
    readingArtifact.value = null;
  }
);
watch(
  () => runState.value?.lastResearchUpdate,
  (update) => {
    const mapping: Record<string, 'evidence' | 'claims' | 'sections' | 'artifacts'> = {
      'research.evidence.updated': 'evidence',
      'research.claims.updated': 'claims',
      'research.section.updated': 'sections',
      'research.draft.updated': 'artifacts',
    };
    if (!update) return;
    if (update.type === 'research.step.updated') void store.refreshSteps();
    if (mapping[update.type]) void store.refreshResource(mapping[update.type]);
  }
);
watch(
  isRunActive,
  (active) => {
    if (elapsedTimer) clearInterval(elapsedTimer);
    elapsedTimer = null;
    if (!active) return;
    displayNow.value = Date.now();
    elapsedTimer = setInterval(() => {
      displayNow.value = Date.now();
    }, 1000);
  },
  { immediate: true }
);
watch(
  () => runState.value?.usage,
  () => {
    if (runState.value) void store.refreshMetrics();
  }
);
watch(
  () => runState.value?.status,
  () => {
    if (runState.value) void store.refreshMetrics();
  }
);
watch(
  () => store.plan,
  (plan) => {
    editableSteps.value = plan
      ? plan.steps.map((step) => ({ ...step, sources: [...step.sources] }))
      : [];
  },
  { immediate: true }
);
async function createProject() {
  await store.create({
    ...form,
    sources: [...form.sources],
    output_formats: [...form.output_formats],
  });
  showCreate.value = false;
  form.title = '';
  form.objective = '';
}
async function downloadArtifact(artifact: Record<string, unknown>) {
  const blob = await fetchArtifact(String(artifact.download_url || ''));
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = String(artifact.filename || 'research-artifact');
  link.click();
  URL.revokeObjectURL(url);
}
async function deleteArtifact(artifact: Record<string, unknown>) {
  const filename = String(artifact.filename || '此交付物');
  if (!window.confirm(`删除“${filename}”吗？此操作不可撤销。`)) return;
  await store.deleteArtifact(String(artifact.id));
  previewExpanded.value = false;
  editingMarkdown.value = false;
}
async function savePlan() {
  await store.savePlan(editableSteps.value);
}
async function uploadAttachment(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (file) await store.uploadAttachment(file);
  input.value = '';
}
async function deleteProject() {
  if (window.confirm('删除这个研究项目？历史 Run 与交付物将不再显示。')) {
    await store.deleteSelected();
  }
}
async function openMarkdownEditor(artifact: Record<string, unknown>) {
  const projectId = store.selectedId;
  const markdown = await (await fetchArtifact(String(artifact.download_url || ''))).text();
  if (projectId !== store.selectedId) return;
  readingArtifact.value = null;
  markdownDraft.value = markdown;
  editingMarkdown.value = true;
}
async function openReport(artifact: Record<string, unknown>) {
  const projectId = store.selectedId;
  const markdown = await (await fetchArtifact(String(artifact.download_url || ''))).text();
  if (projectId !== store.selectedId) return;
  readingArtifact.value = artifact;
  markdownDraft.value = markdown;
  editingMarkdown.value = false;
  previewExpanded.value = true;
  await nextTick();
  expandedPreviewDialogRef.value?.focus();
}
async function openExpandedPreview() {
  previewExpanded.value = true;
  await nextTick();
  expandedPreviewDialogRef.value?.focus();
}
async function closeExpandedPreview() {
  previewExpanded.value = false;
  await nextTick();
  previewExpandButtonRef.value?.focus();
}
async function exportPdf() {
  const created = await store.reviseMarkdown(markdownDraft.value);
  const pdf = created.find((artifact) => artifact.media_type === 'application/pdf');
  if (pdf) await downloadArtifact(pdf);
}
function closeMarkdownEditor() {
  previewExpanded.value = false;
  editingMarkdown.value = false;
}
async function saveMarkdown() {
  await store.reviseMarkdown(markdownDraft.value);
  closeMarkdownEditor();
}
onMounted(() => store.loadProjects());
onUnmounted(() => {
  if (elapsedTimer) clearInterval(elapsedTimer);
});
</script>

<style scoped>
.research-markdown :deep(.research-citation) {
  padding: 0 3px;
  color: var(--accent, #a8dcca);
  background: transparent;
  border: 0;
  text-decoration: underline;
  cursor: pointer;
  font: inherit;
}
.citation-content {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  line-height: 1.7;
}
.citation-detail:focus-visible {
  outline: 2px solid var(--accent, #a8dcca);
  outline-offset: 3px;
}
.research-workbench {
  width: 100%;
  height: 100%;
  overflow: auto;
  padding: 28px;
  color: var(--text, #f7f7fb);
  font-size: var(--font-small);
}
.research-header,
.project-overview-header,
.detail-heading,
.actions,
.metric-row,
.card-heading,
.row,
.artifact-row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.research-header {
  justify-content: space-between;
  margin-bottom: 18px;
  padding: 0 2px 20px;
  border-bottom: 1px solid var(--line);
}
.research-header h1 {
  margin-top: 4px;
  font-size: 28px;
  letter-spacing: -0.045em;
}
.research-header p {
  margin-top: 7px;
  color: var(--muted);
  font-size: var(--font-small);
}
.research-grid {
  display: grid;
  grid-template-columns: minmax(236px, 288px) minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}
.research-detail {
  display: grid;
  gap: 14px;
}
.research-card {
  padding: 18px;
  border: 1px solid var(--line-strong, rgba(157, 140, 255, 0.22));
  border-radius: var(--radius-lg, 18px);
  background: var(--surface-strong, rgba(20, 22, 35, 0.9));
  box-shadow: var(--card-shadow, 0 14px 35px rgba(0, 0, 0, 0.12));
}
.card-eyebrow {
  display: block;
  color: var(--lilac, #aa9cff);
  font-size: var(--font-micro);
  font-weight: 700;
  letter-spacing: 0.13em;
}
.primary {
  border: 0;
  border-radius: 10px;
  padding: 10px 16px;
  background: var(--lilac-strong, #8068ff);
  color: #fff;
  cursor: pointer;
  font-size: var(--font-caption);
  font-weight: 700;
  transition:
    transform 0.16s ease,
    box-shadow 0.16s ease,
    background 0.16s ease;
}
.primary:hover:not(:disabled) {
  background: #947fff;
  box-shadow: 0 10px 22px rgba(128, 104, 255, 0.27);
  transform: translateY(-1px);
}
.primary:disabled,
.secondary-button:disabled,
.text-button:disabled {
  cursor: not-allowed;
  opacity: 0.52;
}
.project-list {
  display: flex;
  flex-direction: column;
  gap: 7px;
  align-self: start;
  padding: 12px;
  position: sticky;
  top: 0;
}
.project-list-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 3px 5px 9px;
  color: var(--text-soft);
  font-size: var(--font-caption);
  font-weight: 700;
}
.project-list-heading small {
  color: var(--muted);
  font-size: var(--font-micro);
  font-weight: 500;
}
.project-list button {
  text-align: left;
  padding: 12px;
  border: 1px solid var(--line, transparent);
  border-radius: var(--radius-md, 13px);
  background: var(--surface-soft, transparent);
  color: inherit;
  cursor: pointer;
  transition:
    border-color 0.16s ease,
    background 0.16s ease,
    transform 0.16s ease;
}
.project-list strong {
  display: block;
  overflow: hidden;
  font-size: var(--font-small);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.project-list button.active {
  border-color: var(--lilac-strong, #8f7cff);
  background: linear-gradient(135deg, rgba(168, 246, 209, 0.13), rgba(142, 121, 255, 0.17));
  box-shadow: inset 0 0 0 1px rgba(168, 246, 209, 0.18);
}
.project-list button:hover:not(.active) {
  border-color: var(--line-strong);
  background: var(--surface-hover);
  transform: translateY(-1px);
}
.project-list small,
.job-state {
  display: block;
  margin-top: 5px;
  color: var(--muted, #aeb3c2);
  font-size: var(--font-micro);
}
.create-form {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 15px 18px;
  margin-bottom: 18px;
}
.create-heading {
  display: grid;
  gap: 4px;
  grid-column: 1 / -1;
  padding-bottom: 2px;
}
.create-heading strong {
  font-size: var(--font-title-sm);
}
.create-heading small {
  color: var(--muted);
}
.create-form label {
  display: grid;
  gap: 7px;
  color: var(--text-soft);
  font-size: var(--font-caption);
  font-weight: 600;
}
.create-form label:nth-child(2) {
  grid-column: 1/-1;
}
.create-form input,
.create-form textarea,
.create-form select,
.plan-editor input,
.plan-editor textarea,
.markdown-editor textarea {
  padding: 10px;
  border: 1px solid var(--line-strong, rgba(255, 255, 255, 0.15));
  border-radius: var(--radius-sm, 9px);
  background: var(--surface-soft, rgba(0, 0, 0, 0.18));
  color: inherit;
  font-size: var(--font-caption);
}
.create-form input:focus,
.create-form textarea:focus,
.create-form select:focus,
.plan-editor input:focus,
.plan-editor textarea:focus,
.markdown-editor textarea:focus {
  border-color: var(--lilac-strong, #8f7cff);
  outline: none;
}
.create-form input::placeholder,
.create-form textarea::placeholder,
.plan-editor input::placeholder,
.plan-editor textarea::placeholder,
.markdown-editor textarea::placeholder {
  color: var(--muted, #8d93a7);
}
.checkboxes {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}
.checkboxes label {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 7px 9px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: var(--surface-soft);
  color: var(--text-soft);
  cursor: pointer;
  font-weight: 500;
}
.checkboxes input {
  accent-color: var(--lilac-strong, #8068ff);
}
.create-submit {
  justify-self: start;
  min-width: 120px;
}
.status-chip {
  flex: none;
  padding: 6px 10px;
  border-radius: 999px;
  background: rgba(94, 220, 176, 0.14);
  color: var(--success, #6ee0b7);
  font-size: var(--font-micro);
}
.research-error {
  margin-bottom: 14px;
  padding: 12px 14px;
  border: 1px solid rgba(255, 93, 117, 0.24);
  border-radius: var(--radius-md, 13px);
  background: rgba(255, 93, 117, 0.12);
  color: var(--danger, #ff8ea0);
}
.project-overview {
  padding: 20px;
}
.project-overview-header {
  align-items: flex-start;
  justify-content: space-between;
}
.project-intro {
  min-width: 0;
}
.research-card h2 {
  margin-top: 4px;
  font-size: 21px;
  letter-spacing: -0.035em;
}
.project-intro p {
  max-width: 780px;
  margin-top: 6px;
  color: var(--text-soft);
  font-size: var(--font-small);
  line-height: 1.55;
}
.research-card h3 {
  margin: 0;
  font-size: var(--font-title-sm);
  letter-spacing: -0.02em;
}
.research-card h3 span {
  color: var(--muted);
  font-size: var(--font-caption);
  font-weight: 500;
}
.actions {
  flex-wrap: wrap;
}
.primary-actions {
  margin-top: 18px;
  padding-top: 16px;
  border-top: 1px solid var(--line);
}
.secondary-button,
.text-button,
.row-actions button,
.artifact-row > button:not(.artifact-link),
.markdown-editor .actions button:not(.primary) {
  padding: 8px 11px;
  border: 1px solid var(--line-strong);
  border-radius: 9px;
  background: var(--surface-soft);
  color: var(--text-soft);
  cursor: pointer;
  font-size: var(--font-caption);
  transition:
    border-color 0.16s ease,
    background 0.16s ease,
    color 0.16s ease;
}
.secondary-button:hover:not(:disabled),
.text-button:hover:not(:disabled),
.row-actions button:hover:not(:disabled),
.artifact-row > button:not(.artifact-link):hover:not(:disabled),
.markdown-editor .actions button:not(.primary):hover:not(:disabled) {
  border-color: var(--lilac-strong);
  background: var(--surface-hover);
  color: var(--text);
}
.plan-editor {
  margin: 14px 0 16px;
  padding: 0;
  list-style: none;
}
.plan-editor li {
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr);
  gap: 12px;
  padding: 14px 0;
  border-bottom: 1px solid var(--line);
}
.plan-editor li:last-child {
  border-bottom: 0;
  padding-bottom: 0;
}
.step-number {
  display: grid;
  width: 30px;
  height: 30px;
  place-items: center;
  border: 1px solid var(--line-strong);
  border-radius: 9px;
  background: linear-gradient(135deg, rgba(168, 246, 209, 0.14), rgba(142, 121, 255, 0.16));
  color: var(--mint);
  font-size: var(--font-micro);
  font-weight: 700;
}
.step-fields {
  display: grid;
  gap: 8px;
}
.step-fields label {
  display: grid;
  gap: 5px;
  color: var(--muted);
  font-size: var(--font-micro);
  font-weight: 600;
}
.source-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.source-tags span,
.step-count,
.attachment-status {
  border-radius: 999px;
  background: var(--surface-soft);
  color: var(--text-soft);
  font-size: var(--font-micro);
}
.source-tags span {
  padding: 3px 8px;
  border: 1px solid var(--line);
}
.card-heading {
  justify-content: space-between;
  margin-bottom: 4px;
}
.card-heading .card-eyebrow {
  margin-bottom: 3px;
}
.step-count {
  padding: 5px 8px;
  white-space: nowrap;
}
.save-plan-button {
  margin-top: 2px;
}
.upload-button {
  padding: 9px 12px;
  border: 1px solid var(--line-strong, rgba(255, 255, 255, 0.16));
  border-radius: 9px;
  background: var(--surface-soft);
  color: var(--text-soft);
  cursor: pointer;
  font-size: var(--font-caption);
  transition:
    border-color 0.16s ease,
    background 0.16s ease;
}
.upload-button:hover {
  border-color: var(--mint-strong);
  background: var(--surface-hover);
}
.upload-button input {
  display: none;
}
.secondary-actions {
  margin-top: 12px;
}
.danger {
  padding: 8px 2px;
  border: 0;
  background: transparent;
  color: var(--danger, #ff8ea0);
  cursor: pointer;
  font-size: var(--font-caption);
}
.danger:hover {
  text-decoration: underline;
}
.row,
.artifact-row {
  justify-content: space-between;
  padding: 10px 0;
  border-bottom: 1px solid var(--line);
}
.row:last-child,
.artifact-row:last-child {
  border-bottom: 0;
  padding-bottom: 0;
}
.attachment-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.attachment-status {
  margin-left: auto;
  padding: 4px 8px;
}
.row-actions {
  display: flex;
  flex: none;
  gap: 8px;
}
.run-card .detail-heading {
  justify-content: space-between;
}
.metric-row {
  justify-content: flex-start;
  margin-top: 14px;
}
.metric-row span {
  min-width: 105px;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: var(--radius-md, 13px);
  background: var(--surface-soft);
  color: var(--muted);
  font-size: var(--font-caption);
}
.metric-row b {
  margin-right: 4px;
  color: var(--mint);
  font-size: var(--font-title-sm);
}
.run-phase {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  margin-top: 15px;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: var(--radius-md, 13px);
  background: linear-gradient(135deg, rgba(168, 246, 209, 0.1), rgba(142, 121, 255, 0.11));
}
.run-phase-dot {
  width: 9px;
  height: 9px;
  flex: none;
  margin-top: 5px;
  border-radius: 50%;
  background: var(--lilac, #aa9cff);
  box-shadow: 0 0 0 4px rgba(170, 156, 255, 0.12);
}
.run-phase.is-running .run-phase-dot,
.run-phase.is-pending .run-phase-dot {
  background: var(--mint, #a8f6d1);
  animation: research-pulse 1.5s ease-in-out infinite;
}
.run-phase.is-failed .run-phase-dot,
.run-phase.is-cancelled .run-phase-dot {
  background: var(--danger, #ff8ea0);
}
.run-phase strong {
  display: block;
  color: var(--text);
  font-size: var(--font-caption);
}
.run-phase p,
.research-muted {
  margin: 4px 0 0;
  color: var(--muted);
  font-size: var(--font-caption);
  line-height: 1.55;
}
.run-metrics {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}
.run-metrics span {
  display: grid;
  min-width: 0;
  gap: 4px;
}
.run-metrics small {
  overflow: hidden;
  color: var(--muted);
  font-size: var(--font-micro);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.run-metrics b {
  margin: 0;
  overflow: hidden;
  color: var(--text);
  font-size: var(--font-caption);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.run-steps {
  display: grid;
  gap: 0;
  margin: 16px 0 0;
  padding: 0;
  list-style: none;
}
.run-steps li {
  position: relative;
  padding: 0 0 15px;
}
.run-steps li:not(:last-child)::before {
  position: absolute;
  top: 31px;
  bottom: 0;
  left: 14px;
  width: 1px;
  background: var(--line);
  content: '';
}
.run-step-marker {
  z-index: 1;
  display: grid;
  width: 29px;
  height: 29px;
  place-items: center;
  border: 1px solid var(--line-strong);
  border-radius: 50%;
  background: var(--surface-strong);
  color: var(--muted);
  font-size: var(--font-micro);
  font-weight: 700;
}
.run-step-trigger {
  display: grid;
  width: 100%;
  grid-template-columns: 30px minmax(0, 1fr);
  gap: 10px;
  padding: 0;
  border: 0;
  background: transparent;
  color: inherit;
  cursor: pointer;
  text-align: left;
}
.run-step-trigger:hover .run-step-copy,
.run-steps li.selected .run-step-copy {
  background: var(--surface-hover);
}
.run-step-trigger:focus-visible {
  border-radius: var(--radius-md, 13px);
  outline: 2px solid var(--lilac);
  outline-offset: 3px;
}
.run-steps li.is-running .run-step-marker {
  border-color: var(--mint);
  background: rgba(168, 246, 209, 0.15);
  color: var(--mint);
}
.run-steps li.is-completed .run-step-marker {
  border-color: var(--lilac);
  background: rgba(170, 156, 255, 0.15);
  color: var(--lilac);
}
.run-steps li.is-degraded .run-step-marker,
.run-steps li.is-failed .run-step-marker {
  border-color: var(--danger);
  color: var(--danger);
}
.run-step-copy {
  display: grid;
  gap: 4px;
  min-width: 0;
  padding: 3px 7px;
  border-radius: var(--radius-sm, 9px);
  transition: background 0.16s ease;
}
.run-step-copy > span:first-child {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.run-step-copy strong {
  min-width: 0;
  overflow: hidden;
  color: var(--text);
  font-size: var(--font-caption);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.run-step-copy em {
  flex: none;
  color: var(--muted);
  font-size: var(--font-micro);
  font-style: normal;
}
.run-steps li.is-running .run-step-copy em {
  color: var(--mint);
}
.run-step-question {
  display: -webkit-box;
  overflow: hidden;
  color: var(--text-soft);
  font-size: var(--font-micro);
  line-height: 1.5;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}
.run-step-copy small {
  color: var(--muted);
  font-size: var(--font-micro);
}
.step-evidence-panel {
  margin: 2px 0 16px 40px;
  padding: 13px;
  border: 1px solid var(--line-strong);
  border-radius: var(--radius-md, 13px);
  background: var(--surface-soft);
}
.step-evidence-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.step-evidence-heading strong {
  display: block;
  margin-top: 3px;
  color: var(--text);
  font-size: var(--font-caption);
}
.step-evidence-heading > span {
  flex: none;
  color: var(--muted);
  font-size: var(--font-micro);
}
.step-evidence-list {
  display: grid;
  gap: 9px;
  margin: 12px 0 0;
  padding: 0;
  list-style: none;
}
.step-evidence-list li {
  display: grid;
  grid-template-columns: max-content minmax(0, 1fr);
  gap: 8px;
  padding: 10px;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm, 9px);
  background: var(--surface-strong);
}
.evidence-citation {
  color: var(--lilac);
  font-size: var(--font-micro);
  font-weight: 700;
}
.step-evidence-list strong {
  display: block;
  color: var(--text-soft);
  font-size: var(--font-caption);
}
.step-evidence-list p {
  margin: 4px 0;
  color: var(--muted);
  font-size: var(--font-micro);
  line-height: 1.55;
}
.step-evidence-list small {
  color: var(--muted);
  font-size: var(--font-micro);
}
.run-warnings {
  margin-top: 3px;
  border-top: 1px solid var(--line);
  color: var(--muted);
  font-size: var(--font-micro);
}
.run-warnings summary {
  padding-top: 11px;
  cursor: pointer;
}
.run-warnings p {
  margin: 7px 0 0;
}
@keyframes research-pulse {
  50% {
    opacity: 0.45;
    transform: scale(0.78);
  }
}
.markdown-editor {
  display: grid;
  gap: 10px;
  margin-top: 12px;
}
.markdown-editor textarea {
  width: 100%;
}
.markdown-editor-panels {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 12px;
}
.markdown-source,
.markdown-preview {
  display: grid;
  gap: 7px;
  min-width: 0;
  color: var(--text-soft);
  font-size: var(--font-caption);
  font-weight: 600;
}
.markdown-source textarea {
  min-height: 360px;
  resize: vertical;
}
.markdown-preview {
  max-height: 430px;
  overflow: auto;
  padding: 10px 12px;
  border: 1px solid var(--line-strong, rgba(255, 255, 255, 0.15));
  border-radius: var(--radius-sm, 9px);
  background: var(--surface-soft, rgba(0, 0, 0, 0.18));
}
.markdown-preview-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.preview-expand-button {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 9px;
  border: 1px solid var(--line-strong);
  border-radius: 8px;
  color: var(--text-soft);
  background: var(--surface);
  cursor: pointer;
  font-size: var(--font-micro);
}
.preview-expand-button:hover {
  border-color: var(--lilac-strong);
  color: var(--text);
}
.markdown-preview .research-markdown {
  margin-top: 0;
  font-weight: 400;
}
.report-preview-backdrop {
  position: fixed;
  z-index: 1000;
  inset: 0;
  display: grid;
  place-items: center;
  padding: 24px;
  background: rgba(5, 7, 14, 0.72);
  backdrop-filter: blur(16px);
}
.report-preview-dialog {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  width: min(1180px, 100%);
  height: min(860px, calc(100vh - 48px));
  overflow: hidden;
  border: 1px solid var(--line-strong);
  border-radius: 24px;
  color: var(--text);
  background:
    radial-gradient(circle at 92% 3%, rgba(103, 217, 173, 0.1), transparent 30%),
    radial-gradient(circle at 5% 2%, rgba(142, 121, 255, 0.12), transparent 30%),
    var(--surface-strong);
  box-shadow: var(--shadow);
}
.report-preview-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  padding: 22px 24px 18px;
  border-bottom: 1px solid var(--line);
}
.report-preview-header h2 {
  margin-top: 6px;
  font-size: 24px;
  letter-spacing: -0.04em;
}
.report-preview-header p {
  margin-top: 6px;
  color: var(--muted);
  font-size: var(--font-small);
}
.report-preview-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}
.report-preview-actions > button {
  cursor: pointer;
}
.report-preview-export {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  white-space: nowrap;
}
.report-preview-close {
  display: grid;
  width: 36px;
  height: 36px;
  flex: none;
  place-items: center;
  border: 1px solid var(--line);
  border-radius: 11px;
  color: var(--muted);
  background: var(--surface);
}
.report-preview-content {
  overflow: auto;
  padding: 24px clamp(24px, 5vw, 64px) 48px;
}
.report-preview-content .research-markdown {
  width: min(880px, 100%);
  margin: 0 auto;
  font-size: var(--font-ui);
  font-weight: 400;
  line-height: 1.75;
}
.research-markdown {
  margin-top: 10px;
  line-height: 1.65;
}
.research-markdown :deep(h1),
.research-markdown :deep(h2),
.research-markdown :deep(h3),
.research-markdown :deep(h4),
.research-markdown :deep(h5),
.research-markdown :deep(h6) {
  margin: 1.25em 0 0.55em;
  color: var(--text);
}
.research-markdown :deep(h1) {
  font-size: 1.35em;
}
.research-markdown :deep(h2) {
  font-size: 1.22em;
}
.research-markdown :deep(h3) {
  font-size: 1.1em;
}
.research-markdown :deep(p),
.research-markdown :deep(ul),
.research-markdown :deep(ol),
.research-markdown :deep(blockquote) {
  margin: 0.7em 0;
}
.research-markdown :deep(ul),
.research-markdown :deep(ol) {
  padding-left: 1.4em;
}
.research-markdown :deep(li + li) {
  margin-top: 0.28em;
}
.research-markdown :deep(pre) {
  overflow: auto;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm, 9px);
  background: var(--surface-soft);
  white-space: pre-wrap;
}
.research-markdown :deep(code) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}
.research-markdown :deep(:not(pre) > code) {
  padding: 0.12em 0.32em;
  border-radius: 4px;
  background: var(--surface-soft);
}
.research-markdown :deep(table) {
  width: 100%;
  border-collapse: collapse;
}
.research-markdown :deep(th),
.research-markdown :deep(td) {
  padding: 7px 9px;
  border: 1px solid var(--line);
  text-align: left;
}
.research-markdown :deep(a) {
  color: var(--lilac);
}
.content-card details {
  padding: 11px 0;
  border-bottom: 1px solid var(--line);
}
.content-card details:last-child {
  border-bottom: 0;
  padding-bottom: 0;
}
.content-card summary {
  color: var(--text-soft);
  cursor: pointer;
  font-weight: 600;
}
.artifact-row {
  align-items: center;
}
.artifact-link {
  min-width: 0;
  overflow: hidden;
  text-align: left;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.empty-detail {
  min-height: 180px;
  display: grid;
  place-items: center;
  color: var(--muted, #aeb3c2);
}
@media (max-width: 900px) {
  .research-workbench {
    padding: 18px;
  }
  .research-grid {
    grid-template-columns: 1fr;
  }
  .create-form {
    grid-template-columns: 1fr;
  }
  .create-form label:nth-child(2) {
    grid-column: auto;
  }
  .project-list {
    position: static;
  }
}
@media (max-width: 620px) {
  .research-workbench {
    padding: 14px;
  }
  .research-header,
  .project-overview-header {
    align-items: flex-start;
    flex-direction: column;
  }
  .metric-row {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 8px;
  }
  .run-metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .metric-row span {
    min-width: 0;
    padding: 9px;
  }
  .row,
  .artifact-row {
    align-items: flex-start;
    flex-wrap: wrap;
  }
  .attachment-status {
    margin-left: 0;
  }
  .row-actions {
    width: 100%;
  }
  .markdown-editor-panels {
    grid-template-columns: 1fr;
  }
  .report-preview-backdrop {
    padding: 10px;
  }
  .report-preview-dialog {
    height: calc(100vh - 20px);
    border-radius: 16px;
  }
  .report-preview-header {
    padding: 17px;
  }
  .report-preview-header p {
    display: none;
  }
  .report-preview-content {
    padding: 18px;
  }
}
.artifact-link {
  display: block;
  padding: 8px 0;
  border: 0;
  background: transparent;
  color: var(--lilac, #aa9cff);
  cursor: pointer;
}
</style>

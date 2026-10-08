import { defineStore } from 'pinia';
import { useRunsStore } from '@/stores/runs';
import { createIdempotencyKey, getRun } from '@/runs/runClient';
import type {
  ResearchPlanStepV1,
  ResearchPlanV1,
  ResearchProjectV1,
} from '@/types/generated/research-api-v1';
import {
  approveResearchProject,
  cancelPlanJob,
  cloneResearchProject,
  createPlanJob,
  createResearchProject,
  deleteResearchArtifact,
  deleteResearchAttachment,
  deleteResearchProject,
  getPlanJob,
  getResearchPlan,
  getResearchProject,
  getResearchMetrics,
  listResearchProjects,
  listResearchAttachments,
  listResearchResources,
  listResearchSteps,
  rerunResearchProject,
  retryResearchAttachment,
  reviseResearchMarkdown,
  updateResearchPlan,
  uploadResearchAttachment,
  type CreateResearchProject,
  type ResearchPlanJob,
  type ResearchMetrics,
  type ResearchResource,
  type ResearchStepResource,
} from '@/research/researchClient';
import { useAuthStore } from '@/stores/auth';
import { getPublicError } from '@/utils/api';

const TERMINAL_JOB_STATUSES = new Set(['cancelled', 'completed', 'failed']);
const TERMINAL_RUN_STATUSES = new Set(['succeeded', 'completed', 'failed', 'cancelled']);
const RESEARCH_RUN_REFRESH_INTERVAL_MS = 2000;
const RESEARCH_PLAN_REFRESH_INTERVAL_MS = 1200;
const polling = new WeakMap<
  object,
  { timer: ReturnType<typeof setTimeout> | null; controller: AbortController | null }
>();
const runPolling = new WeakMap<object, { timer: ReturnType<typeof setTimeout> | null }>();

function pollState(store: object) {
  let state = polling.get(store);
  if (!state) {
    state = { timer: null, controller: null };
    polling.set(store, state);
  }
  return state;
}

function runPollState(store: object) {
  let state = runPolling.get(store);
  if (!state) {
    state = { timer: null };
    runPolling.set(store, state);
  }
  return state;
}

export const useResearchStore = defineStore('research', {
  state: () => ({
    projects: [] as ResearchProjectV1[],
    selectedId: '' as string,
    plan: null as ResearchPlanV1 | null,
    planJob: null as ResearchPlanJob | null,
    evidence: [] as ResearchResource[],
    claims: [] as ResearchResource[],
    steps: [] as ResearchStepResource[],
    sections: [] as ResearchResource[],
    artifacts: [] as ResearchResource[],
    attachments: [] as ResearchResource[],
    metrics: null as ResearchMetrics | null,
    loading: false,
    busy: false,
    error: '',
    scopeVersion: 0,
  }),
  getters: {
    selected(state): ResearchProjectV1 | null {
      return state.projects.find((project) => project.id === state.selectedId) || null;
    },
  },
  actions: {
    stopPolling() {
      const state = pollState(this);
      if (state.timer) clearTimeout(state.timer);
      state.timer = null;
      state.controller?.abort();
      state.controller = null;
    },
    stopRunPolling() {
      const state = runPollState(this);
      if (state.timer) clearTimeout(state.timer);
      state.timer = null;
    },
    reset() {
      this.stopPolling();
      this.stopRunPolling();
      this.scopeVersion += 1;
      this.projects = [];
      this.selectedId = '';
      this.plan = null;
      this.planJob = null;
      this.evidence = [];
      this.claims = [];
      this.steps = [];
      this.sections = [];
      this.artifacts = [];
      this.attachments = [];
      this.metrics = null;
      this.loading = false;
      this.busy = false;
      this.error = '';
    },
    async loadProjects() {
      const scope = this.scopeVersion;
      this.loading = true;
      this.error = '';
      try {
        const projects = await listResearchProjects();
        if (scope !== this.scopeVersion) return;
        this.projects = projects;
        if (!this.selectedId && projects[0]) await this.select(projects[0].id);
      } catch (error) {
        if (scope === this.scopeVersion) this.error = getPublicError(error).message;
      } finally {
        if (scope === this.scopeVersion) this.loading = false;
      }
    },
    async create(command: CreateResearchProject) {
      this.busy = true;
      this.error = '';
      try {
        const project = await createResearchProject(command);
        this.projects = [project, ...this.projects];
        await this.select(project.id);
      } catch (error) {
        this.error = getPublicError(error).message;
        throw error;
      } finally {
        this.busy = false;
      }
    },
    async select(projectId: string) {
      this.stopPolling();
      this.stopRunPolling();
      this.selectedId = projectId;
      this.plan = null;
      this.planJob = null;
      this.evidence = [];
      this.claims = [];
      this.steps = [];
      this.sections = [];
      this.artifacts = [];
      this.attachments = [];
      this.metrics = null;
      const scope = this.scopeVersion;
      this.loading = true;
      try {
        const project = await getResearchProject(projectId);
        if (scope !== this.scopeVersion || this.selectedId !== projectId) return;
        this.replaceProject(project);
        if (project.lifecycle_status !== 'draft') {
          await this.loadPlan(projectId);
        }
        if (scope !== this.scopeVersion || this.selectedId !== projectId) return;
        const attachments = await listResearchAttachments(projectId);
        if (scope !== this.scopeVersion || this.selectedId !== projectId) return;
        this.attachments = attachments;
        if (project.latest_run_id) {
          await this.connectRun(project);
          await this.refreshResources(projectId);
        }
      } catch (error) {
        const publicError = getPublicError(error);
        if (
          scope === this.scopeVersion &&
          this.selectedId === projectId &&
          publicError.code !== 'NOT_FOUND'
        )
          this.error = publicError.message;
      } finally {
        if (scope === this.scopeVersion && this.selectedId === projectId) this.loading = false;
      }
    },
    replaceProject(project: ResearchProjectV1) {
      const index = this.projects.findIndex((candidate) => candidate.id === project.id);
      if (index < 0) this.projects = [project, ...this.projects];
      else this.projects.splice(index, 1, project);
    },
    async generatePlan() {
      const project = this.selected;
      if (!project) return;
      this.busy = true;
      this.error = '';
      try {
        this.planJob = await createPlanJob(project, createIdempotencyKey('run'));
        this.pollPlanJob(project.id, this.planJob.id, this.scopeVersion);
      } catch (error) {
        this.error = getPublicError(error).message;
      } finally {
        this.busy = false;
      }
    },
    pollPlanJob(projectId: string, jobId: string, scope: number) {
      this.stopPolling();
      const schedule = (delayMs = RESEARCH_PLAN_REFRESH_INTERVAL_MS) => {
        const state = pollState(this);
        state.timer = setTimeout(async () => {
          if (scope !== this.scopeVersion || projectId !== this.selectedId) return;
          state.controller = new AbortController();
          try {
            const job = await getPlanJob(projectId, jobId, state.controller.signal);
            if (scope !== this.scopeVersion || projectId !== this.selectedId) return;
            this.error = '';
            this.planJob = job;
            if (TERMINAL_JOB_STATUSES.has(job.status)) {
              state.controller = null;
              if (job.status === 'completed') {
                await this.loadPlan(projectId);
                const project = await getResearchProject(projectId);
                this.replaceProject(project);
              } else if (job.error_code) {
                this.error = `计划生成失败：${job.error_code}`;
              }
              return;
            }
            schedule();
          } catch (error) {
            if (state.controller?.signal.aborted) return;
            const publicError = getPublicError(error);
            this.error = publicError.message;
            if (publicError.retryable) schedule();
          } finally {
            state.controller = null;
          }
        }, delayMs);
      };
      schedule(0);
    },
    async cancelPlan() {
      const project = this.selected;
      if (!project || !this.planJob) return;
      this.stopPolling();
      this.planJob = await cancelPlanJob(project.id, this.planJob.id);
    },
    async loadPlan(projectId: string) {
      const scope = this.scopeVersion;
      const plan = await getResearchPlan(projectId);
      if (scope === this.scopeVersion && this.selectedId === projectId) this.plan = plan;
    },
    async savePlan(steps: ResearchPlanStepV1[]) {
      const project = this.selected;
      if (!project) return;
      const scope = this.scopeVersion;
      this.busy = true;
      this.error = '';
      try {
        const plan = await updateResearchPlan(project, steps);
        const updated = await getResearchProject(project.id);
        if (scope !== this.scopeVersion || project.id !== this.selectedId) return;
        this.plan = plan;
        this.replaceProject(updated);
      } catch (error) {
        if (scope === this.scopeVersion && project.id === this.selectedId)
          this.error = getPublicError(error).message;
      } finally {
        if (scope === this.scopeVersion && project.id === this.selectedId) this.busy = false;
      }
    },
    async approve() {
      const project = this.selected;
      if (!project || !this.plan) return;
      const scope = this.scopeVersion;
      this.busy = true;
      this.error = '';
      try {
        const approval = await approveResearchProject(project, createIdempotencyKey('run'));
        if (scope !== this.scopeVersion || project.id !== this.selectedId) return;
        this.replaceProject(approval.project);
        await this.connectRun({ ...approval.project, latest_run_id: approval.run_id });
        await this.refreshResources(project.id);
      } catch (error) {
        if (scope === this.scopeVersion && project.id === this.selectedId)
          this.error = getPublicError(error).message;
      } finally {
        if (scope === this.scopeVersion && project.id === this.selectedId) this.busy = false;
      }
    },
    async connectRun(project: ResearchProjectV1) {
      if (!project.latest_run_id) return;
      const scope = this.scopeVersion;
      const runs = useRunsStore();
      const record = await getRun(project.latest_run_id, useAuthStore().token);
      if (scope !== this.scopeVersion || project.id !== this.selectedId) return;
      runs.ensure(record.id, record.thread_id);
      runs.hydrate(record.id, record);
      if (!TERMINAL_RUN_STATUSES.has(record.status)) {
        this.pollRunProgress(project.id, record.id, this.scopeVersion);
        void runs
          .connect(record.id)
          .then(async () => {
            if (project.id !== this.selectedId || this.selected?.latest_run_id !== record.id)
              return;
            this.stopRunPolling();
            await this.refreshAfterRun(project.id);
          })
          .catch(() => undefined);
      }
    },
    pollRunProgress(projectId: string, runId: string, scope: number) {
      this.stopRunPolling();
      const schedule = () => {
        const state = runPollState(this);
        state.timer = setTimeout(async () => {
          if (scope !== this.scopeVersion || projectId !== this.selectedId) return;
          try {
            const runs = useRunsStore();
            const record = await runs.get(runId, useAuthStore().token);
            if (scope !== this.scopeVersion || projectId !== this.selectedId) return;
            await this.refreshResources(projectId);
            if (TERMINAL_RUN_STATUSES.has(record.status)) {
              await this.refreshAfterRun(projectId);
              this.stopRunPolling();
              return;
            }
          } catch {
            // SSE remains the primary transport; the next bounded refresh can recover a transient failure.
          }
          if (scope === this.scopeVersion && projectId === this.selectedId) schedule();
        }, RESEARCH_RUN_REFRESH_INTERVAL_MS);
      };
      schedule();
    },
    async rerun() {
      const project = this.selected;
      if (!project) return;
      const scope = this.scopeVersion;
      this.busy = true;
      this.error = '';
      try {
        const approval = await rerunResearchProject(project, createIdempotencyKey('run'));
        if (scope !== this.scopeVersion || project.id !== this.selectedId) return;
        this.replaceProject(approval.project);
        this.evidence = [];
        this.claims = [];
        this.steps = [];
        this.sections = [];
        this.metrics = null;
        await this.connectRun({ ...approval.project, latest_run_id: approval.run_id });
        await this.refreshResources(project.id);
      } catch (error) {
        if (scope === this.scopeVersion && project.id === this.selectedId)
          this.error = getPublicError(error).message;
      } finally {
        if (scope === this.scopeVersion && project.id === this.selectedId) this.busy = false;
      }
    },
    async cloneSelected() {
      const project = this.selected;
      if (!project) return;
      const cloned = await cloneResearchProject(project.id);
      this.projects = [cloned, ...this.projects];
      await this.select(cloned.id);
    },
    async deleteSelected() {
      const project = this.selected;
      if (!project) return;
      await deleteResearchProject(project.id);
      this.projects = this.projects.filter((candidate) => candidate.id !== project.id);
      const next = this.projects[0];
      if (next) await this.select(next.id);
      else this.reset();
    },
    async refreshAfterRun(projectId: string) {
      if (projectId !== this.selectedId) return;
      const project = await getResearchProject(projectId);
      this.replaceProject(project);
      await this.refreshResources(projectId);
    },
    async refreshResources(projectId?: string) {
      const scope = this.scopeVersion;
      const targetProjectId = projectId || this.selectedId;
      if (!targetProjectId) return;
      const runId = this.selected?.latest_run_id;
      const [evidence, claims, sections, artifacts, attachments, steps, metrics] =
        await Promise.all([
          listResearchResources(targetProjectId, 'evidence'),
          listResearchResources(targetProjectId, 'claims'),
          listResearchResources(targetProjectId, 'sections'),
          listResearchResources(targetProjectId, 'artifacts'),
          listResearchAttachments(targetProjectId),
          runId ? listResearchSteps(targetProjectId, runId) : Promise.resolve([]),
          runId ? getResearchMetrics(targetProjectId, runId) : Promise.resolve(null),
        ]);
      if (
        scope !== this.scopeVersion ||
        targetProjectId !== this.selectedId ||
        runId !== this.selected?.latest_run_id
      )
        return;
      this.evidence = evidence;
      this.claims = claims;
      this.steps = steps;
      this.sections = sections;
      this.artifacts = artifacts;
      this.attachments = attachments;
      this.metrics = metrics;
    },
    async refreshResource(resource: 'evidence' | 'claims' | 'sections' | 'artifacts') {
      const scope = this.scopeVersion;
      const projectId = this.selectedId;
      const runId = this.selected?.latest_run_id;
      if (!projectId) return;
      const items = await listResearchResources(projectId, resource);
      if (
        scope !== this.scopeVersion ||
        projectId !== this.selectedId ||
        runId !== this.selected?.latest_run_id
      )
        return;
      this[resource] = items;
    },
    async refreshSteps() {
      const project = this.selected;
      if (!project?.latest_run_id) return;
      const items = await listResearchSteps(project.id, project.latest_run_id);
      if (project.id !== this.selectedId || project.latest_run_id !== this.selected?.latest_run_id)
        return;
      this.steps = items;
    },
    async refreshMetrics() {
      const project = this.selected;
      if (!project?.latest_run_id) return;
      const metrics = await getResearchMetrics(project.id, project.latest_run_id);
      if (project.id !== this.selectedId || project.latest_run_id !== this.selected?.latest_run_id)
        return;
      this.metrics = metrics;
    },
    async uploadAttachment(file: File) {
      const project = this.selected;
      if (!project) return;
      this.busy = true;
      try {
        await uploadResearchAttachment(project.id, file);
        this.replaceProject(await getResearchProject(project.id));
        this.attachments = await listResearchAttachments(project.id);
      } catch (error) {
        this.error = getPublicError(error).message;
      } finally {
        this.busy = false;
      }
    },
    async retryAttachment(attachmentId: string) {
      if (!this.selectedId) return;
      await retryResearchAttachment(this.selectedId, attachmentId);
      this.attachments = await listResearchAttachments(this.selectedId);
    },
    async deleteAttachment(attachmentId: string) {
      if (!this.selectedId) return;
      await deleteResearchAttachment(this.selectedId, attachmentId);
      this.attachments = await listResearchAttachments(this.selectedId);
    },
    async deleteArtifact(artifactId: string) {
      if (!this.selectedId) return;
      this.busy = true;
      try {
        await deleteResearchArtifact(this.selectedId, artifactId);
        this.artifacts = await listResearchResources(this.selectedId, 'artifacts');
      } catch (error) {
        this.error = getPublicError(error).message;
        throw error;
      } finally {
        this.busy = false;
      }
    },
    async reviseMarkdown(markdown: string): Promise<ResearchResource[]> {
      if (!this.selectedId) return [];
      this.busy = true;
      try {
        const created = await reviseResearchMarkdown(this.selectedId, markdown, true);
        this.artifacts = await listResearchResources(this.selectedId, 'artifacts');
        return created;
      } catch (error) {
        this.error = getPublicError(error).message;
        throw error;
      } finally {
        this.busy = false;
      }
    },
  },
});

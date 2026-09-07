import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  createPlanJob,
  getResearchPlan,
  getResearchProject,
  getResearchMetrics,
  getPlanJob,
  listResearchAttachments,
  listResearchProjects,
  listResearchResources,
  listResearchSteps,
  reviseResearchMarkdown,
} from '@/research/researchClient';
import { getRun } from '@/runs/runClient';
import { useResearchStore } from './research';

vi.mock('@/research/researchClient', () => ({
  approveResearchProject: vi.fn(),
  cancelPlanJob: vi.fn(),
  createPlanJob: vi.fn(),
  createResearchProject: vi.fn(),
  getPlanJob: vi.fn(),
  getResearchMetrics: vi.fn(),
  getResearchPlan: vi.fn(),
  getResearchProject: vi.fn(),
  listResearchAttachments: vi.fn(),
  listResearchProjects: vi.fn(),
  listResearchResources: vi.fn(),
  listResearchSteps: vi.fn(),
  reviseResearchMarkdown: vi.fn(),
}));

vi.mock('@/runs/runClient', () => ({
  createIdempotencyKey: vi.fn(() => 'research-idempotency-key'),
  getRun: vi.fn(),
}));

function project() {
  return {
    id: 'rproj_0123456789abcdef0123456789abcdef',
    thread_id: 'research:thread',
    title: '研究项目',
    objective: '研究知渊',
    mode: 'quick' as const,
    lifecycle_status: 'draft' as const,
    version: 1,
    run_status: null,
    latest_run_id: null,
    created_at: '2026-09-02T00:00:00Z',
    updated_at: '2026-09-02T00:00:00Z',
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

describe('research store account scope and polling lifecycle', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
    vi.useRealTimers();
  });

  it('drops a stale project response after account scope reset', async () => {
    const pending = deferred<ReturnType<typeof project>[]>();
    vi.mocked(listResearchProjects).mockReturnValue(pending.promise);
    const store = useResearchStore();

    const loading = store.loadProjects();
    store.reset();
    pending.resolve([project()]);
    await loading;

    expect(store.projects).toEqual([]);
    expect(store.selectedId).toBe('');
  });

  it('clears Plan Job polling when the account scope resets', async () => {
    vi.useFakeTimers();
    const initial = project();
    vi.mocked(createPlanJob).mockResolvedValue({
      id: 'rpjob_0123456789abcdef0123456789abcdef',
      project_id: initial.id,
      status: 'pending',
      fencing_token: 0,
      attempts: 0,
      result_plan_id: null,
      error_code: null,
      created_at: initial.created_at,
      updated_at: initial.updated_at,
    });
    const store = useResearchStore();
    store.projects = [initial];
    store.selectedId = initial.id;

    await store.generatePlan();
    store.reset();
    await vi.advanceTimersByTimeAsync(2000);

    expect(getPlanJob).not.toHaveBeenCalled();
    expect(store.planJob).toBeNull();
  });

  it('loads the completed plan and approval state without a page refresh', async () => {
    vi.useFakeTimers();
    const initial = project();
    const job = {
      id: 'rpjob_0123456789abcdef0123456789abcdef',
      project_id: initial.id,
      status: 'completed' as const,
      fencing_token: 1,
      attempts: 1,
      result_plan_id: 'rplan_0123456789abcdef0123456789abcdef',
      error_code: null,
      created_at: initial.created_at,
      updated_at: initial.updated_at,
    };
    const plan = {
      id: job.result_plan_id,
      project_id: initial.id,
      version: 1,
      objective: initial.objective,
      steps: [
        {
          step_key: 'scope',
          title: '明确范围',
          question: '需要核验哪些事实？',
          sources: ['knowledge_base' as const],
        },
      ],
      created_at: initial.created_at,
    };
    const awaitingApproval = {
      ...initial,
      lifecycle_status: 'awaiting_approval' as const,
      version: 2,
    };
    vi.mocked(createPlanJob).mockResolvedValue({ ...job, status: 'pending' });
    vi.mocked(getPlanJob).mockResolvedValue(job);
    vi.mocked(getResearchPlan).mockResolvedValue(plan);
    vi.mocked(getResearchProject).mockResolvedValue(awaitingApproval);
    const store = useResearchStore();
    store.projects = [initial];
    store.selectedId = initial.id;

    await store.generatePlan();
    await vi.advanceTimersByTimeAsync(0);

    expect(store.plan).toEqual(plan);
    expect(store.selected?.lifecycle_status).toBe('awaiting_approval');
    expect(getPlanJob).toHaveBeenCalledOnce();
  });

  it('returns the newly generated PDF artifact after revising Markdown', async () => {
    const created = [
      {
        id: 'art_pdf',
        logical_type: 'report_pdf',
        media_type: 'application/pdf',
        download_url: '/api/artifacts/art_pdf',
      },
    ];
    vi.mocked(reviseResearchMarkdown).mockResolvedValue(created);
    vi.mocked(listResearchResources).mockResolvedValue(created);
    const store = useResearchStore();
    store.selectedId = project().id;

    await expect(store.reviseMarkdown('# 报告')).resolves.toEqual(created);
    expect(reviseResearchMarkdown).toHaveBeenCalledWith(project().id, '# 报告', true);
    expect(store.artifacts).toEqual(created);
  });

  it('stores persisted research metrics when refreshing resources', async () => {
    const selected = { ...project(), latest_run_id: 'run_research_metrics' };
    const metrics = {
      run_count: 1,
      evidence_count: 2,
      claim_count: 1,
      section_count: 1,
      input_tokens: 100,
      output_tokens: 200,
      model_calls: 2,
      duration_ms: 1000,
      elapsed_ms: 2000,
    };
    vi.mocked(listResearchResources).mockResolvedValue([]);
    vi.mocked(listResearchAttachments).mockResolvedValue([]);
    vi.mocked(listResearchSteps).mockResolvedValue([]);
    vi.mocked(getResearchMetrics).mockResolvedValue(metrics);
    const store = useResearchStore();
    store.projects = [selected];
    store.selectedId = selected.id;

    await store.refreshResources();

    expect(store.metrics).toEqual(metrics);
  });

  it('refreshes an active Run when the event stream is unavailable and stops on reset', async () => {
    vi.useFakeTimers();
    const selected = { ...project(), latest_run_id: 'run_research_poll' };
    vi.mocked(getRun).mockResolvedValue({
      id: selected.latest_run_id,
      thread_id: selected.thread_id,
      channel: 'research',
      status: 'running',
      idempotency_key: 'key',
      user_message_id: 1,
      assistant_message_id: 2,
      on_disconnect: 'continue',
    });
    vi.mocked(listResearchResources).mockResolvedValue([]);
    vi.mocked(listResearchAttachments).mockResolvedValue([]);
    vi.mocked(listResearchSteps).mockResolvedValue([]);
    vi.mocked(getResearchMetrics).mockResolvedValue({
      run_count: 1,
      evidence_count: 0,
      claim_count: 0,
      section_count: 0,
      input_tokens: 0,
      output_tokens: 0,
      model_calls: 0,
      duration_ms: 0,
      elapsed_ms: 0,
    });
    const store = useResearchStore();
    store.projects = [selected];
    store.selectedId = selected.id;

    store.pollRunProgress(selected.id, selected.latest_run_id, store.scopeVersion);
    await vi.advanceTimersByTimeAsync(2000);

    expect(getRun).toHaveBeenCalledWith(selected.latest_run_id, expect.any(String));
    expect(getResearchMetrics).toHaveBeenCalledWith(selected.id, selected.latest_run_id);

    store.reset();
    await vi.advanceTimersByTimeAsync(4000);
    expect(getRun).toHaveBeenCalledTimes(1);
  });
});

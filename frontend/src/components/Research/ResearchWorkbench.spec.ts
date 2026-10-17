// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from 'vitest';
import { createApp, nextTick, type App } from 'vue';
import ResearchWorkbench from './ResearchWorkbench.vue';
import { fetchArtifact } from '@/artifacts/artifactClient';
import type {
  ResearchMetrics,
  ResearchResource,
  ResearchStepResource,
} from '@/research/researchClient';

const state = vi.hoisted(() => ({
  research: {
    projects: [
      {
        id: 'rproj_0123456789abcdef0123456789abcdef',
        thread_id: 'research:thread',
        title: '知渊研究体验',
        objective: '梳理研究工作台的可用性和后续优化方向。',
        mode: 'quick',
        lifecycle_status: 'awaiting_approval',
        version: 1,
        run_status: null,
        latest_run_id: null as string | null,
        created_at: '2026-09-03T00:00:00Z',
        updated_at: '2026-09-03T00:00:00Z',
      },
    ],
    selected: {
      id: 'rproj_0123456789abcdef0123456789abcdef',
      thread_id: 'research:thread',
      title: '知渊研究体验',
      objective: '梳理研究工作台的可用性和后续优化方向。',
      mode: 'quick',
      lifecycle_status: 'awaiting_approval',
      version: 1,
      run_status: null,
      latest_run_id: null as string | null,
      created_at: '2026-09-03T00:00:00Z',
      updated_at: '2026-09-03T00:00:00Z',
    },
    selectedId: 'rproj_0123456789abcdef0123456789abcdef',
    plan: {
      id: 'rplan_0123456789abcdef0123456789abcdef',
      project_id: 'rproj_0123456789abcdef0123456789abcdef',
      version: 1,
      objective: '梳理研究工作台的可用性和后续优化方向。',
      steps: [
        {
          step_key: 'scope',
          title: '明确研究范围',
          question: '需要核验哪些核心事实？',
          sources: ['knowledge_base', 'web'],
        },
      ],
      created_at: '2026-09-03T00:00:00Z',
    },
    planJob: null,
    evidence: [] as ResearchResource[],
    claims: [] as ResearchResource[],
    steps: [] as ResearchStepResource[],
    sections: [] as ResearchResource[],
    artifacts: [] as ResearchResource[],
    attachments: [{ id: 'attachment_1', filename: 'research-brief.pdf', status: 'indexed' }],
    metrics: null as ResearchMetrics | null,
    loading: false,
    busy: false,
    error: '',
    loadProjects: vi.fn(),
    select: vi.fn(),
    generatePlan: vi.fn(),
    cancelPlan: vi.fn(),
    approve: vi.fn(),
    cloneSelected: vi.fn(),
    rerun: vi.fn(),
    deleteSelected: vi.fn(),
    savePlan: vi.fn(),
    uploadAttachment: vi.fn(),
    retryAttachment: vi.fn(),
    deleteAttachment: vi.fn(),
    deleteArtifact: vi.fn(),
    reviseMarkdown: vi.fn(),
    refreshResource: vi.fn(),
    refreshSteps: vi.fn(),
    refreshMetrics: vi.fn(),
  },
  runs: { byId: {}, cancel: vi.fn() },
}));

vi.mock('@/stores/research', () => ({
  useResearchStore: () => state.research,
}));
vi.mock('@/stores/runs', () => ({
  useRunsStore: () => state.runs,
}));
vi.mock('@/artifacts/artifactClient', () => ({
  fetchArtifact: vi.fn(),
}));

describe('ResearchWorkbench', () => {
  let app: App<Element> | null = null;
  let root: HTMLDivElement | null = null;

  it('discloses degraded delivery after a canonical completed event', async () => {
    const runId = 'run_degraded';
    state.research.selected.latest_run_id = runId;
    state.research.sections = [
      { id: 'section', title: '结论', status: 'degraded', content_markdown: '仍需核验' },
    ];
    state.runs.byId = {
      [runId]: { status: 'completed', hasGap: false, warnings: [], usage: {}, activeDurationMs: 0 },
    };
    root = document.createElement('div');
    document.body.appendChild(root);
    app = createApp(ResearchWorkbench);
    app.mount(root);
    await nextTick();
    expect(root.querySelector('.run-phase')?.textContent).toContain('部分内容降级');
    expect(root.querySelector('.run-phase')?.textContent).toContain('交付完成不代表全部事实已验证');
    expect(root.textContent).not.toContain('Run 已创建，正在准备研究步骤');
  });

  it('blocks approval while the displayed plan has unsaved edits', async () => {
    state.research.selected.lifecycle_status = 'awaiting_approval';
    root = document.createElement('div');
    document.body.appendChild(root);
    app = createApp(ResearchWorkbench);
    app.mount(root);
    await nextTick();
    const approve = [...root.querySelectorAll('button')].find((button) =>
      button.textContent?.includes('批准并开始研究')
    );
    expect(approve?.disabled).toBe(false);
    const input = root.querySelector<HTMLInputElement>('[aria-label="步骤标题"]');
    input!.value = '新的研究范围';
    input!.dispatchEvent(new Event('input', { bubbles: true }));
    await nextTick();
    expect(approve?.disabled).toBe(true);
    expect(root.textContent).toContain('计划有未保存修改');
    approve?.click();
    expect(state.research.approve).not.toHaveBeenCalled();
  });

  it('opens persisted evidence from a chapter citation without rendering source HTML', async () => {
    state.research.sections = [
      {
        id: 'section',
        title: '成本',
        status: 'completed',
        content_markdown: '每月成本为 500 元 [E1]。',
      },
    ];
    state.research.evidence = [
      {
        id: 'evidence',
        citation: 'E1',
        title: '官方价格',
        content: '<script>alert(1)</script>每月 500 元。',
        source_uri: 'https://example.com/pricing',
      },
    ];
    root = document.createElement('div');
    document.body.appendChild(root);
    app = createApp(ResearchWorkbench);
    app.mount(root);
    await nextTick();
    const citation = root.querySelector<HTMLButtonElement>('[data-citation="E1"]');
    expect(citation).not.toBeNull();
    citation?.click();
    await nextTick();
    expect(root.querySelector('.citation-detail')?.textContent).toContain('官方价格');
    expect(root.querySelector('.citation-detail')?.textContent).toContain('每月 500 元');
    expect(root.querySelector('.citation-detail script')).toBeNull();
    expect(root.querySelector('.citation-detail a')?.getAttribute('href')).toBe(
      'https://example.com/pricing'
    );
  });

  afterEach(() => {
    app?.unmount();
    root?.remove();
    app = null;
    root = null;
  });

  it('renders the structured project overview and readable research-plan sources', async () => {
    root = document.createElement('div');
    document.body.appendChild(root);
    app = createApp(ResearchWorkbench);
    app.mount(root);
    await nextTick();

    expect(root.querySelector('.project-list-heading')?.textContent).toContain('研究项目');
    expect(root.querySelector('.project-overview .card-eyebrow')?.textContent).toContain(
      'QUICK RESEARCH'
    );
    expect(root.querySelector('.status-chip')?.textContent).toContain('等待批准');
    expect(root.querySelectorAll('.step-number')).toHaveLength(1);
    expect(root.querySelector('.source-tags')?.textContent).toContain('知识库');
    expect(root.querySelector('.source-tags')?.textContent).toContain('Web');
    expect(root.querySelector('.attachment-status')?.textContent).toContain('已索引');
  });

  it('renders run-scoped duration, token usage, and persisted step progress', async () => {
    const runId = 'run_research_progress';
    state.research.selected.latest_run_id = runId;
    state.research.steps = [
      {
        id: 'rstep_progress',
        run_id: runId,
        step_key: 'scope',
        position: 1,
        status: 'completed',
        evidence_count: 4,
        evidence_ids: ['rev_1', 'rev_2', 'rev_3', 'rev_4'],
        source_stats: {
          web: { candidate_count: 6, evidence_count: 4, filtered_count: 2, error_count: 0 },
        },
        started_at: '2026-09-03T00:00:00Z',
        finished_at: '2026-09-03T00:00:12Z',
        updated_at: '2026-09-03T00:00:12Z',
      },
    ];
    state.research.metrics = {
      run_count: 1,
      evidence_count: 4,
      claim_count: 1,
      section_count: 1,
      input_tokens: 1250,
      output_tokens: 460,
      model_calls: 3,
      duration_ms: 9600,
      elapsed_ms: 12000,
      run_budget_seconds: 300,
    };
    state.research.evidence = [
      {
        id: 'rev_1',
        citation: 'E1',
        title: 'Agent 框架的官方资料',
        content: '该资料说明了框架的工作流编排、状态管理和可观测性能力。',
        source_kind: 'web',
        domain: 'example.com',
        quality_score: 0.92,
      },
    ];
    state.runs.byId = {
      [runId]: {
        status: 'running',
        hasGap: false,
        warnings: [],
        usage: { input_tokens: 1250, output_tokens: 460 },
        activeDurationMs: 0,
      },
    };
    root = document.createElement('div');
    document.body.appendChild(root);
    app = createApp(ResearchWorkbench);
    app.mount(root);
    await nextTick();

    expect(root.querySelector('.run-card')?.textContent).toContain('运行耗时');
    expect(root.querySelector('.run-card')?.textContent).toContain('12 秒');
    expect(root.querySelector('.run-card')?.textContent).toContain('1250 / 460');
    expect(root.querySelector('.run-budget-note')?.textContent).toContain('5 分 00 秒');
    expect(root.querySelector('.run-budget-note')?.textContent).toContain('可提前阅读');
    expect(root.querySelector('.run-step-copy')?.textContent).toContain('4 条证据');
    expect(root.querySelector('.run-step-copy')?.textContent).toContain('已完成');

    const trigger = root.querySelector('.run-step-trigger');
    expect(trigger?.getAttribute('aria-expanded')).toBe('false');
    trigger?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    await nextTick();

    expect(root.querySelector('.run-step-trigger')?.getAttribute('aria-expanded')).toBe('true');
    expect(root.querySelector('.step-evidence-panel')?.textContent).toContain(
      'Agent 框架的官方资料'
    );
    expect(root.querySelector('.step-evidence-panel')?.textContent).toContain('[E1]');
    expect(root.querySelector('.step-evidence-panel')?.textContent).toContain('example.com');
    expect(root.querySelector('.step-evidence-panel')?.textContent).toContain(
      'Web：候选 6，保留 4，过滤 2，错误 0'
    );
  });

  it('falls back to persisted section citations for historical runs without step evidence IDs', async () => {
    state.research.steps = [
      {
        ...state.research.steps[0],
        evidence_ids: [],
      },
    ];
    state.research.sections = [
      {
        id: 'rsection_legacy',
        section_key: 'scope',
        title: '明确研究范围',
        status: 'completed',
        evidence_ids: ['rev_legacy'],
      },
    ];
    state.research.evidence = [
      {
        id: 'rev_legacy',
        citation: 'E8',
        title: '旧 Run 已保存的章节证据',
        content: '该证据通过章节引用与研究步骤关联。',
        source_kind: 'attachments',
      },
    ];
    root = document.createElement('div');
    document.body.appendChild(root);
    app = createApp(ResearchWorkbench);
    app.mount(root);
    await nextTick();

    root
      .querySelector('.run-step-trigger')
      ?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    await nextTick();

    expect(root.querySelector('.step-evidence-panel')?.textContent).toContain(
      '旧 Run 已保存的章节证据'
    );
    expect(root.querySelector('.step-evidence-panel')?.textContent).toContain('附件');
  });

  it('renders persisted section Markdown through the shared sanitizer', async () => {
    state.research.sections = [
      {
        id: 'rsection_markdown',
        title: '研究结论',
        status: 'completed',
        content_markdown:
          '## 已核验事实\n\n- 支持 **Markdown** 渲染。\n\n<script>alert(1)</script>',
      },
    ];
    root = document.createElement('div');
    document.body.appendChild(root);
    app = createApp(ResearchWorkbench);
    app.mount(root);
    await nextTick();

    const section = root.querySelector('.research-markdown');
    expect(section?.querySelector('h2')?.textContent).toBe('已核验事实');
    expect(section?.querySelector('strong')?.textContent).toBe('Markdown');
    expect(section?.querySelector('script')).toBeNull();
  });

  it('shows a sanitized Markdown preview and expands it into a readable dialog', async () => {
    state.research.artifacts = [
      {
        id: 'art_report_preview',
        filename: 'research-report.md',
        media_type: 'text/markdown',
        state: 'final',
        version: 1,
        download_url: '/api/artifacts/art_report_preview',
      },
    ];
    vi.mocked(fetchArtifact)
      .mockResolvedValueOnce({
        text: async () =>
          '# 企业选型建议\n\n**LangGraph** 适合长运行工作流。<script>alert(1)</script>',
      } as Blob)
      .mockResolvedValueOnce(new Blob(['pdf'], { type: 'application/pdf' }));
    state.research.reviseMarkdown.mockResolvedValue([
      {
        id: 'art_report_pdf',
        filename: 'research-report.pdf',
        media_type: 'application/pdf',
        state: 'final',
        version: 1,
        download_url: '/api/artifacts/art_report_pdf',
      },
    ]);
    const downloadClick = vi
      .spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(() => undefined);
    root = document.createElement('div');
    document.body.appendChild(root);
    app = createApp(ResearchWorkbench);
    app.mount(root);
    await nextTick();

    const edit = [...root.querySelectorAll('button')].find(
      (button) => button.textContent?.trim() === '编辑'
    );
    expect(edit).toBeDefined();
    edit?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    await vi.waitFor(() =>
      expect(root?.querySelector('.markdown-preview h1')?.textContent).toBe('企业选型建议')
    );

    expect(root.querySelector('.markdown-preview strong')?.textContent).toBe('LangGraph');
    expect(root.querySelector('.markdown-preview script')).toBeNull();

    const expand = root.querySelector<HTMLButtonElement>('[aria-label="放大报告预览"]');
    expand?.click();
    await nextTick();

    const dialog = document.body.querySelector<HTMLElement>('.report-preview-dialog');
    expect(dialog?.getAttribute('aria-modal')).toBe('true');
    expect(dialog?.querySelector('h1')?.textContent).toBe('企业选型建议');
    expect(dialog?.querySelector('strong')?.textContent).toBe('LangGraph');
    expect(dialog?.querySelector('script')).toBeNull();
    expect(document.activeElement).toBe(dialog);

    const exportButton = [...(dialog?.querySelectorAll('button') || [])].find((button) =>
      button.textContent?.includes('导出 PDF')
    );
    exportButton?.click();
    await vi.waitFor(() =>
      expect(state.research.reviseMarkdown).toHaveBeenCalledWith(
        '# 企业选型建议\n\n**LangGraph** 适合长运行工作流。<script>alert(1)</script>'
      )
    );
    await vi.waitFor(() => {
      expect(fetchArtifact).toHaveBeenLastCalledWith('/api/artifacts/art_report_pdf');
      expect(downloadClick).toHaveBeenCalledOnce();
    });
    downloadClick.mockRestore();

    dialog?.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    await nextTick();
    expect(document.body.querySelector('.report-preview-dialog')).toBeNull();
    expect(document.activeElement).toBe(expand);
  });

  it('reads the saved report and returns from citations without creating a revision', async () => {
    state.research.artifacts = [
      {
        id: 'art_read',
        filename: 'report.md',
        media_type: 'text/markdown',
        state: 'final',
        version: 1,
        download_url: '/api/artifacts/art_read',
      },
    ];
    state.research.evidence = [
      { id: 'evidence', citation: 'E1', title: '原始材料', content: '原文内容' },
    ];
    state.research.reviseMarkdown.mockClear();
    vi.mocked(fetchArtifact).mockResolvedValueOnce({
      text: async () => '# 报告\n\n已保存结论 [E1]。',
    } as Blob);
    root = document.createElement('div');
    document.body.appendChild(root);
    app = createApp(ResearchWorkbench);
    app.mount(root);
    await nextTick();
    const read = [...root.querySelectorAll('button')].find(
      (button) => button.textContent?.trim() === '阅读报告'
    );
    expect(read).toBeDefined();
    read?.click();
    await vi.waitFor(() =>
      expect(document.body.querySelector('.report-preview-dialog h1')?.textContent).toBe('报告')
    );
    const dialog = document.body.querySelector('.report-preview-dialog');
    expect(dialog?.textContent).not.toContain('导出 PDF');
    dialog?.querySelector<HTMLButtonElement>('[data-citation="E1"]')?.click();
    await nextTick();
    expect(root.querySelector('.citation-detail')?.textContent).toContain('原文内容');
    expect(document.body.querySelector('.report-preview-dialog')).toBeNull();
    root.querySelector<HTMLButtonElement>('.citation-detail button')?.click();
    await nextTick();
    await nextTick();
    expect(document.body.querySelector('.report-preview-dialog')).not.toBeNull();
    expect(document.activeElement?.getAttribute('data-citation')).toBe('E1');
    expect(state.research.reviseMarkdown).not.toHaveBeenCalled();
  });

  it('confirms and deletes an individual research artifact', async () => {
    state.research.artifacts = [
      {
        id: 'art_report_delete',
        filename: 'research-report.md',
        media_type: 'text/markdown',
        state: 'final',
        version: 1,
        download_url: '/api/artifacts/art_report_delete',
      },
    ];
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    root = document.createElement('div');
    document.body.appendChild(root);
    app = createApp(ResearchWorkbench);
    app.mount(root);
    await nextTick();

    const remove = root.querySelector('.artifact-row .danger');
    remove?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    await vi.waitFor(() =>
      expect(state.research.deleteArtifact).toHaveBeenCalledWith('art_report_delete')
    );
  });
});

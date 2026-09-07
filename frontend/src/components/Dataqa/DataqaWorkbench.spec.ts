// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from 'vitest';
import { createApp, nextTick, reactive, type App } from 'vue';
import type { DataQaQuery } from '@/dataqa/dataqaClient';

const dataQaStore = vi.hoisted(() => ({ current: null as unknown }));

vi.mock('@/stores/dataqa', () => ({
  useDataQaStore: () => dataQaStore.current,
}));

import DataqaWorkbench from './DataqaWorkbench.vue';

const query = (): DataQaQuery => ({
  id: 'qa_0123456789abcdef',
  question: '2026 年每个月的销售额分别是多少？',
  status: 'completed',
  run_id: 'run_0123456789abcdef',
  error_code: null,
  version: 1,
  created_at: '2026-09-02T00:00:00Z',
  updated_at: '2026-09-02T00:00:00Z',
  result: {
    sql: 'SELECT sale_month, total_sales FROM analytics.orders;',
    tables: [],
    columns: ['sale_month', 'total_sales'],
    rows: [
      ['2026-01-01T00:00:00+00:00', '29483.00'],
      ['2026-02-01T00:00:00+00:00', '29482.00'],
      ['2026-03-01T00:00:00+00:00', '41373.00'],
    ],
    row_count: 3,
    truncated: false,
    chart: { chart_type: 'none', label_field: '', value_field: '' },
    analysis: '**关键发现**\n\n| 月份 | 销售额 |\n| --- | ---: |\n| 2026-03 | 41,373 |',
  },
});

function storeFor(current: DataQaQuery) {
  return reactive({
    queries: [current],
    selectedId: current.id,
    selected: current,
    questionDraft: '',
    analysisBusy: false,
    loading: false,
    busy: false,
    error: '',
    deletingId: '',
    select: vi.fn(),
    ask: vi.fn(),
    loadQueries: vi.fn(),
    generateAnalysis: vi.fn(),
    deleteQuery: vi.fn(),
  });
}

describe('DataqaWorkbench', () => {
  let app: App<Element> | null = null;
  let root: HTMLDivElement | null = null;
  const execCommandDescriptor = Object.getOwnPropertyDescriptor(document, 'execCommand');
  const secureContextDescriptor = Object.getOwnPropertyDescriptor(window, 'isSecureContext');

  afterEach(() => {
    app?.unmount();
    root?.remove();
    app = null;
    root = null;
    vi.restoreAllMocks();
    if (execCommandDescriptor)
      Object.defineProperty(document, 'execCommand', execCommandDescriptor);
    else delete (document as { execCommand?: unknown }).execCommand;
    if (secureContextDescriptor)
      Object.defineProperty(window, 'isSecureContext', secureContextDescriptor);
    else delete (window as { isSecureContext?: unknown }).isSecureContext;
  });

  it('renders legacy numeric-string results as an automatic chart and formats analysis markdown', async () => {
    dataQaStore.current = storeFor(query());
    root = document.createElement('div');
    document.body.appendChild(root);
    app = createApp(DataqaWorkbench);
    app.mount(root);
    await nextTick();

    expect(root.querySelectorAll('.bar')).toHaveLength(3);
    expect(root.querySelector('.chart-empty')).toBeNull();
    expect(root.querySelector('.analysis-text strong')?.textContent).toBe('关键发现');
    expect(root.querySelector('.analysis-text table')).not.toBeNull();

    const chartSelect = root.querySelector<HTMLSelectElement>('.chart-select');
    if (!chartSelect) throw new Error('chart type selector is missing');
    chartSelect.value = 'pie';
    chartSelect.dispatchEvent(new Event('change'));
    await nextTick();

    expect(root.querySelectorAll('.pie-percent')).toHaveLength(3);
    expect(root.textContent).toContain('41%');
  });

  it('falls back to selection copying when the Clipboard API is unavailable', async () => {
    dataQaStore.current = storeFor(query());
    Object.defineProperty(window, 'isSecureContext', { configurable: true, value: false });
    Object.defineProperty(document, 'execCommand', {
      configurable: true,
      value: vi.fn(() => true),
    });
    root = document.createElement('div');
    document.body.appendChild(root);
    app = createApp(DataqaWorkbench);
    app.mount(root);
    await nextTick();

    const copyButton = Array.from(root.querySelectorAll('button')).find((button) =>
      button.textContent?.includes('复制')
    );
    copyButton?.click();
    await nextTick();

    expect(document.execCommand).toHaveBeenCalledWith('copy');
    expect(root.textContent).toContain('已复制');
  });

  it('confirms before deleting a completed query', async () => {
    const store = storeFor(query());
    dataQaStore.current = store;
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    root = document.createElement('div');
    document.body.appendChild(root);
    app = createApp(DataqaWorkbench);
    app.mount(root);
    await nextTick();

    root.querySelector<HTMLButtonElement>('.query-delete')?.click();

    expect(window.confirm).toHaveBeenCalledOnce();
    expect(store.deleteQuery).toHaveBeenCalledWith(store.selectedId);
  });
});

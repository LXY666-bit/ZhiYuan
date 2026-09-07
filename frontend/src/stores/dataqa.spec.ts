import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  createDataQaAnalysis,
  createDataQaQuery,
  deleteDataQaQuery,
  getDataQaQuery,
  listDataQaQueries,
} from '@/dataqa/dataqaClient';
import { useDataQaStore } from './dataqa';
import type { DataQaQuery } from '@/dataqa/dataqaClient';

vi.mock('@/dataqa/dataqaClient', () => ({
  createDataQaAnalysis: vi.fn(),
  createDataQaQuery: vi.fn(),
  deleteDataQaQuery: vi.fn(),
  getDataQaQuery: vi.fn(),
  listDataQaQueries: vi.fn(),
}));

vi.mock('@/runs/runClient', () => ({
  createIdempotencyKey: vi.fn(() => 'dataqa-idempotency-key'),
}));

function query(overrides: Partial<DataQaQuery> = {}): DataQaQuery {
  return {
    id: 'qa_0123456789abcdef',
    question: '销量前五的商品是哪些？',
    status: 'completed',
    run_id: 'run_0123456789abcdef',
    error_code: null,
    version: 1,
    created_at: '2026-09-02T00:00:00Z',
    updated_at: '2026-09-02T00:00:00Z',
    result: {
      sql: 'SELECT 1',
      tables: [],
      columns: ['good_name', 'total_num'],
      rows: [
        ['无线键盘', 128],
        ['无线鼠标', 96],
      ],
      row_count: 2,
      truncated: false,
      chart: {
        chart_type: 'bar',
        label_field: 'good_name',
        value_field: 'total_num',
      },
      analysis: null,
    },
    ...overrides,
  };
}

describe('dataqa store scope and lifecycle', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
    vi.useRealTimers();
  });

  it('selects the first query after loading and keeps selection stable', async () => {
    const first = query();
    const second = query({ id: 'qa_second', status: 'pending', result: null });
    vi.mocked(listDataQaQueries).mockResolvedValue([first, second]);
    const store = useDataQaStore();

    await store.loadQueries();

    expect(store.queries).toEqual([first, second]);
    expect(store.selectedId).toBe(first.id);
    expect(store.selected).toEqual(first);
    expect(store.hasActive).toBe(true);
  });

  it('asks a new question and prepends it with selection', async () => {
    vi.mocked(createDataQaQuery).mockResolvedValue(query({ status: 'pending' }));
    const store = useDataQaStore();

    await store.ask('销量前五的商品是哪些？');

    expect(createDataQaQuery).toHaveBeenCalledWith(
      '销量前五的商品是哪些？',
      'dataqa-idempotency-key'
    );
    expect(store.queries).toHaveLength(1);
    expect(store.selectedId).toBe(store.queries[0].id);
  });

  it('refreshes the selected query in place', async () => {
    const initial = query({ status: 'running', result: null });
    vi.mocked(listDataQaQueries).mockResolvedValue([initial]);
    const store = useDataQaStore();
    await store.loadQueries();
    const completed = query({ version: 2 });
    vi.mocked(getDataQaQuery).mockResolvedValue(completed);

    await store.refreshSelected();

    expect(store.queries[0]).toEqual(completed);
    expect(store.selected?.version).toBe(2);
  });

  it('attaches analysis only once and updates the query in place', async () => {
    const initial = query();
    vi.mocked(listDataQaQueries).mockResolvedValue([initial]);
    const store = useDataQaStore();
    await store.loadQueries();
    const analyzed = query({
      version: 2,
      result: initial.result ? { ...initial.result, analysis: '键盘销量最高。' } : null,
    });
    vi.mocked(createDataQaAnalysis).mockResolvedValue(analyzed);

    await store.generateAnalysis();

    expect(createDataQaAnalysis).toHaveBeenCalledWith(initial.id, 'dataqa-idempotency-key');
    expect(store.queries[0].result?.analysis).toBe('键盘销量最高。');

    // 已有分析时不再发起请求
    await store.generateAnalysis();
    expect(createDataQaAnalysis).toHaveBeenCalledTimes(1);
  });

  it('deletes a completed query and selects the next result', async () => {
    const first = query();
    const second = query({ id: 'qa_second' });
    vi.mocked(listDataQaQueries).mockResolvedValue([first, second]);
    vi.mocked(deleteDataQaQuery).mockResolvedValue();
    const store = useDataQaStore();
    await store.loadQueries();

    await store.deleteQuery(first.id);

    expect(deleteDataQaQuery).toHaveBeenCalledWith(first.id);
    expect(store.queries).toEqual([second]);
    expect(store.selectedId).toBe(second.id);
  });

  it('stops polling once no query is active', async () => {
    vi.mocked(listDataQaQueries).mockResolvedValue([query()]);
    const store = useDataQaStore();

    await store.loadQueries();

    expect(store.hasActive).toBe(false);
    expect(listDataQaQueries).toHaveBeenCalledTimes(1);
  });

  it('drops stale responses after account scope reset', async () => {
    let resolveList: (value: DataQaQuery[]) => void = () => undefined;
    vi.mocked(listDataQaQueries).mockReturnValue(
      new Promise((done) => {
        resolveList = done;
      })
    );
    const store = useDataQaStore();

    const loading = store.loadQueries();
    store.reset();
    resolveList([query()]);
    await loading;

    expect(store.queries).toEqual([]);
    expect(store.selectedId).toBe('');
  });
});

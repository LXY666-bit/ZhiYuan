import { expect, test, type Page } from '@playwright/test';

async function restoreSession(page: Page, role: 'admin' | 'user') {
  await page.route('**/auth/refresh', (route) =>
    route.fulfill({
      json: { access_token: 'dataqa-test-token', username: 'dataqa-user', role },
    })
  );
  await page.route('**/v1/capabilities', (route) =>
    route.fulfill({
      json: { schema_version: 1, catalog_hash: 'f'.repeat(64), skills: [], tools: [] },
    })
  );
  await page.route('**/v1/threads', (route) => route.fulfill({ json: { threads: [] } }));
}

test('ordinary users do not see the admin SQL workbench entry', async ({ page }) => {
  await restoreSession(page, 'user');
  await page.goto('/');
  await expect(page.getByRole('button', { name: '深度研搜', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '智能问数', exact: true })).toHaveCount(0);
});

test('analysis remains pending after HTTP returns and recovers through polling', async ({
  page,
}) => {
  await restoreSession(page, 'admin');
  const query = {
    id: 'qa_test',
    question: '销量多少',
    status: 'completed',
    run_id: 'run_query',
    analysis_run_id: null as string | null,
    analysis_status: null as string | null,
    error_code: null,
    version: 1,
    created_at: '2026-10-15T00:00:00Z',
    updated_at: '2026-10-15T00:00:00Z',
    result: {
      sql: 'SELECT 1 AS total',
      tables: [],
      columns: ['total'],
      rows: [[1]],
      row_count: 1,
      truncated: false,
      chart: { chart_type: 'none', label_field: '', value_field: '' },
      analysis: null as string | null,
    },
  };
  let analysisRequests = 0;
  let finish = false;
  await page.route('**/v1/dataqa/queries', (route) => {
    if (finish) {
      query.analysis_status = 'succeeded';
      query.result.analysis = '当前结果总量为 1。';
    }
    return route.fulfill({ json: { queries: [query] } });
  });
  await page.route('**/v1/dataqa/queries/qa_test/analysis', (route) => {
    analysisRequests += 1;
    expect(route.request().postDataJSON().idempotency_key).toBeTruthy();
    query.analysis_run_id = 'run_analysis';
    query.analysis_status = 'pending';
    return route.fulfill({ json: query });
  });
  await page.goto('/');
  await page.getByRole('button', { name: '智能问数', exact: true }).click();
  await page.getByRole('button', { name: '生成数据分析', exact: true }).click();
  await expect(page.getByRole('button', { name: '生成中…', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: '删除', exact: true })).toBeDisabled();
  expect(analysisRequests).toBe(1);
  finish = true;
  await expect(page.getByText('当前结果总量为 1。', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '删除', exact: true })).toBeEnabled();
  await expect(page.getByRole('button', { name: '生成数据分析', exact: true })).toBeDisabled();
});

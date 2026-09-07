import { expect, test, type Page } from '@playwright/test';

const timestamps = {
  created_at: '2026-09-02T00:00:00Z',
  updated_at: '2026-09-02T00:00:00Z',
};

async function mockShell(page: Page) {
  await page.route('**/auth/refresh', async (route) => {
    await route.fulfill({
      json: { access_token: 'research-e2e-token', username: 'research-user', role: 'user' },
    });
  });
  await page.route('**/v1/capabilities', async (route) => {
    await route.fulfill({
      json: { schema_version: 1, catalog_hash: 'a'.repeat(64), skills: [], tools: [] },
    });
  });
  await page.route('**/v1/threads', async (route) => {
    await route.fulfill({ json: { threads: [] } });
  });
}

test('creates, plans and approves a Quick canonical research Run', async ({ page }) => {
  await mockShell(page);
  const projectId = `rproj_${'1'.repeat(32)}`;
  const planId = `rplan_${'2'.repeat(32)}`;
  const jobId = `rpjob_${'3'.repeat(32)}`;
  const runId = 'run-research-e2e';
  let projectVersion = 1;
  let lifecycle = 'draft';
  let latestRunId: string | null = null;
  let approvedRequest: Record<string, unknown> | null = null;

  const project = () => ({
    id: projectId,
    thread_id: 'research:thread-e2e',
    title: '知渊迁移核验',
    objective: '核验 Research Workbench canonical Run 闭环',
    mode: 'quick',
    lifecycle_status: lifecycle,
    version: projectVersion,
    run_status: latestRunId ? 'succeeded' : null,
    latest_run_id: latestRunId,
    ...timestamps,
  });

  await page.route('**/v1/research/projects', async (route) => {
    if (route.request().method() === 'POST') {
      await route.fulfill({ status: 201, json: project() });
      return;
    }
    await route.fulfill({ json: { projects: [] } });
  });
  await page.route(`**/v1/research/projects/${projectId}`, async (route) => {
    await route.fulfill({ json: project() });
  });
  await page.route(`**/v1/research/projects/${projectId}/attachments`, async (route) => {
    await route.fulfill({ json: { items: [] } });
  });
  await page.route(`**/v1/research/projects/${projectId}/plan-jobs`, async (route) => {
    lifecycle = 'awaiting_approval';
    projectVersion = 2;
    await route.fulfill({
      status: 202,
      json: {
        id: jobId,
        project_id: projectId,
        status: 'pending',
        fencing_token: 0,
        attempts: 0,
        result_plan_id: null,
        error_code: null,
        ...timestamps,
      },
    });
  });
  await page.route(`**/v1/research/projects/${projectId}/plan-jobs/${jobId}`, async (route) => {
    await route.fulfill({
      json: {
        id: jobId,
        project_id: projectId,
        status: 'completed',
        fencing_token: 1,
        attempts: 1,
        result_plan_id: planId,
        error_code: null,
        ...timestamps,
      },
    });
  });
  await page.route(`**/v1/research/projects/${projectId}/plan`, async (route) => {
    await route.fulfill({
      json: {
        plan: {
          id: planId,
          project_id: projectId,
          version: 1,
          objective: project().objective,
          steps: [
            {
              step_key: 'step-1',
              title: '核验架构',
              question: 'Research 是否复用 canonical Run？',
              sources: ['knowledge_base'],
            },
            {
              step_key: 'step-2',
              title: '核验交付',
              question: '是否生成稳定引用和 Artifact？',
              sources: ['knowledge_base'],
            },
          ],
          created_at: timestamps.created_at,
        },
      },
    });
  });
  await page.route(`**/v1/research/projects/${projectId}/approve`, async (route) => {
    approvedRequest = route.request().postDataJSON();
    lifecycle = 'frozen';
    projectVersion = 3;
    latestRunId = runId;
    await route.fulfill({
      status: 202,
      json: { project: project(), run_id: runId, thread_version: 1 },
    });
  });
  await page.route(`**/v1/runs/${runId}`, async (route) => {
    await route.fulfill({
      json: {
        id: runId,
        thread_id: 'research:thread-e2e',
        channel: 'research',
        status: 'succeeded',
      },
    });
  });

  await page.goto('/');
  await page.getByRole('button', { name: '深度研搜' }).click();
  await expect(page.getByRole('heading', { name: '深度研搜' })).toBeVisible();
  await page.getByRole('button', { name: '新建研究' }).click();
  await page.getByLabel('标题').fill('知渊迁移核验');
  await page.getByLabel('研究目标').fill('核验 Research Workbench canonical Run 闭环');
  await page.getByRole('button', { name: '创建', exact: true }).click();

  await expect(page.getByRole('heading', { name: '知渊迁移核验' })).toBeVisible();
  await page.getByRole('button', { name: '生成研究计划' }).click();
  await expect(page.getByText('研究计划 v1')).toBeVisible({ timeout: 5_000 });
  await page.getByRole('button', { name: '批准并开始研究' }).click();

  await expect(page.getByText('succeeded', { exact: true })).toBeVisible();
  const approval = approvedRequest as Record<string, unknown> | null;
  expect(approval).toMatchObject({ expected_project_version: 2 });
  expect(String(approval?.idempotency_key || '')).toContain('run');
});

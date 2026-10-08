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
  let planVersion = 1;
  let firstStepTitle = '核验架构';

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
    if (route.request().method() === 'PUT') {
      const update = route.request().postDataJSON();
      expect(update.expected_project_version).toBe(2);
      firstStepTitle = update.steps[0].title;
      planVersion = 2;
      projectVersion = 3;
    }
    await route.fulfill({
      json: {
        plan: {
          id: planId,
          project_id: projectId,
          version: planVersion,
          objective: project().objective,
          steps: [
            {
              step_key: 'step-1',
              title: firstStepTitle,
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
    projectVersion = 4;
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
  const evidence = [
    {
      id: 'rev_e2e',
      citation: 'E1',
      title: '官方架构资料',
      content: 'Research 复用持久化 Run。',
      source_kind: 'web',
      source_uri: 'https://example.com/research',
    },
  ];
  const resources = {
    evidence,
    claims: [
      {
        id: 'claim_e2e',
        verdict: 'insufficient',
        text: '性能结论需要核验',
        reason: '现有资料没有性能测试。',
      },
    ],
    sections: [
      {
        id: 'section_e2e',
        title: '架构',
        status: 'completed',
        content_markdown: 'Research 复用持久化 Run [E1]。',
      },
    ],
    artifacts: [],
  };
  for (const [resource, items] of Object.entries(resources)) {
    await page.route(`**/v1/research/projects/${projectId}/${resource}`, async (route) => {
      await route.fulfill({ json: { items } });
    });
  }
  await page.route(`**/v1/research/projects/${projectId}/steps?run_id=${runId}`, async (route) => {
    await route.fulfill({ json: { items: [] } });
  });
  await page.route(
    `**/v1/research/projects/${projectId}/metrics?run_id=${runId}`,
    async (route) => {
      await route.fulfill({
        json: {
          metrics: { elapsed_ms: 1000, input_tokens: 100, output_tokens: 50, model_calls: 3 },
        },
      });
    }
  );

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
  await page.getByLabel('步骤标题').first().fill('核验持久化架构');
  await expect(page.getByRole('button', { name: '批准并开始研究' })).toBeDisabled();
  await expect(page.getByText('计划有未保存修改', { exact: false })).toBeVisible();
  await page.getByRole('button', { name: '保存为新计划版本' }).click();
  await expect(page.getByText('研究计划 v2')).toBeVisible();
  await page.getByRole('button', { name: '批准并开始研究' }).click();

  await expect(page.locator('.project-overview .status-chip')).toHaveText('已完成');
  await page.getByText('架构 · completed').click();
  await page.getByRole('button', { name: '查看证据 E1' }).click();
  await expect(page.getByRole('article', { name: '引用证据详情' })).toContainText('官方架构资料');
  await expect(page.getByText('尚未可靠核验 · 性能结论需要核验')).toBeVisible();
  const approval = approvedRequest as Record<string, unknown> | null;
  expect(approval).toMatchObject({ expected_project_version: 3 });
  expect(String(approval?.idempotency_key || '')).toContain('run');
});

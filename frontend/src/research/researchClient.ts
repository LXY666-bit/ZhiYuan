import api, { getPublicError } from '@/utils/api';
import type {
  MarkdownArtifactEditV1,
  ResearchMode,
  ResearchPlanJobStatus,
  ResearchPlanStepV1,
  ResearchPlanV1,
  ResearchProjectV1,
  ResearchSource,
} from '@/types/generated/research-api-v1';

export interface ResearchPlanJob {
  id: string;
  project_id: string;
  status: ResearchPlanJobStatus;
  fencing_token: number;
  attempts: number;
  result_plan_id: string | null;
  error_code: string | null;
  created_at: string;
  updated_at: string;
}

export interface CreateResearchProject {
  title: string;
  objective: string;
  mode: ResearchMode;
  sources: ResearchSource[];
  output_formats: Array<'markdown' | 'pdf'>;
}

export interface ResearchApproval {
  project: ResearchProjectV1;
  run_id: string;
  thread_version: number;
}

export type ResearchResource = Record<string, unknown>;

export interface ResearchSourceStats {
  candidate_count: number;
  evidence_count: number;
  filtered_count: number;
  error_count: number;
}

export interface ResearchStepResource {
  id: string;
  run_id: string;
  step_key: string;
  position: number;
  status: 'pending' | 'running' | 'completed' | 'degraded' | 'failed';
  evidence_count: number;
  evidence_ids: string[];
  source_stats?: Partial<Record<ResearchSource, ResearchSourceStats>>;
  started_at: string | null;
  finished_at: string | null;
  updated_at: string;
}

export interface ResearchMetrics {
  run_count: number;
  evidence_count: number;
  claim_count: number;
  section_count: number;
  input_tokens: number;
  output_tokens: number;
  model_calls: number;
  duration_ms: number;
  elapsed_ms: number;
}

async function request<T>(pending: Promise<{ data: T }>): Promise<T> {
  try {
    return (await pending).data;
  } catch (error) {
    throw getPublicError(error);
  }
}

const projectPath = (projectId: string) => `/v1/research/projects/${encodeURIComponent(projectId)}`;

export function listResearchProjects(signal?: AbortSignal): Promise<ResearchProjectV1[]> {
  return request(
    api.get<{ projects: ResearchProjectV1[] }>('/v1/research/projects', { signal })
  ).then((response) => response.projects);
}

export function createResearchProject(command: CreateResearchProject): Promise<ResearchProjectV1> {
  return request(api.post<ResearchProjectV1>('/v1/research/projects', command));
}

export function cloneResearchProject(projectId: string): Promise<ResearchProjectV1> {
  return request(api.post<ResearchProjectV1>(`${projectPath(projectId)}/clone`));
}

export async function deleteResearchProject(projectId: string): Promise<void> {
  await request(api.delete<void>(projectPath(projectId)));
}

export function getResearchProject(
  projectId: string,
  signal?: AbortSignal
): Promise<ResearchProjectV1> {
  return request(api.get<ResearchProjectV1>(projectPath(projectId), { signal }));
}

export function createPlanJob(
  project: ResearchProjectV1,
  idempotencyKey: string
): Promise<ResearchPlanJob> {
  return request(
    api.post<ResearchPlanJob>(`${projectPath(project.id)}/plan-jobs`, {
      idempotency_key: idempotencyKey,
      expected_project_version: project.version,
    })
  );
}

export function getPlanJob(
  projectId: string,
  jobId: string,
  signal?: AbortSignal
): Promise<ResearchPlanJob> {
  return request(
    api.get<ResearchPlanJob>(`${projectPath(projectId)}/plan-jobs/${encodeURIComponent(jobId)}`, {
      signal,
    })
  );
}

export function cancelPlanJob(projectId: string, jobId: string): Promise<ResearchPlanJob> {
  return request(
    api.post<ResearchPlanJob>(
      `${projectPath(projectId)}/plan-jobs/${encodeURIComponent(jobId)}/cancel`
    )
  );
}

export function getResearchPlan(projectId: string, signal?: AbortSignal): Promise<ResearchPlanV1> {
  return request(
    api.get<{ plan: ResearchPlanV1 }>(`${projectPath(projectId)}/plan`, { signal })
  ).then((response) => response.plan);
}

export function updateResearchPlan(
  project: ResearchProjectV1,
  steps: ResearchPlanStepV1[]
): Promise<ResearchPlanV1> {
  return request(
    api.put<{ plan: ResearchPlanV1 }>(`${projectPath(project.id)}/plan`, {
      expected_project_version: project.version,
      steps,
    })
  ).then((response) => response.plan);
}

export function approveResearchProject(
  project: ResearchProjectV1,
  idempotencyKey: string
): Promise<ResearchApproval> {
  return request(
    api.post<ResearchApproval>(`${projectPath(project.id)}/approve`, {
      expected_project_version: project.version,
      idempotency_key: idempotencyKey,
    })
  );
}

export function rerunResearchProject(
  project: ResearchProjectV1,
  idempotencyKey: string
): Promise<ResearchApproval> {
  return request(
    api.post<ResearchApproval>(`${projectPath(project.id)}/rerun`, {
      expected_project_version: project.version,
      idempotency_key: idempotencyKey,
    })
  );
}

export function listResearchResources(
  projectId: string,
  resource: 'evidence' | 'claims' | 'sections' | 'artifacts',
  signal?: AbortSignal
): Promise<ResearchResource[]> {
  return request(
    api.get<{ items: ResearchResource[] }>(`${projectPath(projectId)}/${resource}`, { signal })
  ).then((response) => response.items);
}

export function listResearchSteps(
  projectId: string,
  runId: string,
  signal?: AbortSignal
): Promise<ResearchStepResource[]> {
  return request(
    api.get<{ items: ResearchStepResource[] }>(`${projectPath(projectId)}/steps`, {
      params: { run_id: runId },
      signal,
    })
  ).then((response) => response.items);
}

export function getResearchMetrics(
  projectId: string,
  runId: string,
  signal?: AbortSignal
): Promise<ResearchMetrics> {
  return request(
    api.get<{ metrics: ResearchMetrics }>(`${projectPath(projectId)}/metrics`, {
      params: { run_id: runId },
      signal,
    })
  ).then((response) => response.metrics);
}

export function listResearchAttachments(
  projectId: string,
  signal?: AbortSignal
): Promise<ResearchResource[]> {
  return request(
    api.get<{ items: ResearchResource[] }>(`${projectPath(projectId)}/attachments`, { signal })
  ).then((response) => response.items);
}

export function uploadResearchAttachment(projectId: string, file: File): Promise<ResearchResource> {
  const body = new FormData();
  body.append('file', file);
  return request(api.post<ResearchResource>(`${projectPath(projectId)}/attachments`, body));
}

export function retryResearchAttachment(
  projectId: string,
  attachmentId: string
): Promise<ResearchResource> {
  return request(
    api.post<ResearchResource>(
      `${projectPath(projectId)}/attachments/${encodeURIComponent(attachmentId)}/retry`
    )
  );
}

export async function deleteResearchAttachment(
  projectId: string,
  attachmentId: string
): Promise<void> {
  await request(
    api.delete<void>(`${projectPath(projectId)}/attachments/${encodeURIComponent(attachmentId)}`)
  );
}

export async function deleteResearchArtifact(projectId: string, artifactId: string): Promise<void> {
  await request(
    api.delete<void>(`${projectPath(projectId)}/artifacts/${encodeURIComponent(artifactId)}`)
  );
}

export function reviseResearchMarkdown(
  projectId: string,
  markdown: string,
  rebuildPdf = true
): Promise<ResearchResource[]> {
  const command: MarkdownArtifactEditV1 = { markdown, rebuild_pdf: rebuildPdf };
  return request(
    api.put<{ items: ResearchResource[] }>(`${projectPath(projectId)}/artifacts/markdown`, command)
  ).then((response) => response.items);
}

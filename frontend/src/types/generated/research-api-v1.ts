// Generated from contracts/research_api_v1.json. Do not edit by hand.
export type ResearchMode = 'quick' | 'standard' | 'deep';
export type ResearchProjectLifecycle = 'draft' | 'awaiting_approval' | 'frozen';
export type ResearchPlanJobStatus = 'pending' | 'running' | 'cancelling' | 'cancelled' | 'completed' | 'failed';
export type ResearchSource = 'knowledge_base' | 'web' | 'attachments';

export interface ResearchPlanStepV1 {
  step_key: string;
  title: string;
  question: string;
  sources: ResearchSource[];
}

export interface ResearchPlanV1 {
  id: string;
  project_id: string;
  version: number;
  objective: string;
  steps: ResearchPlanStepV1[];
  created_at: string;
}

export interface MarkdownArtifactEditV1 {
  markdown: string;
  rebuild_pdf: boolean;
}

export interface ResearchProjectV1 {
  id: string;
  thread_id: string;
  title: string;
  objective: string;
  mode: ResearchMode;
  lifecycle_status: ResearchProjectLifecycle;
  version: number;
  run_status: string | null;
  latest_run_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface RetrievedChunk {
  filename: string;
  page_number?: number;
  text?: string;
  rrf_rank?: number;
  rerank_score?: number;
  score?: number;
}

export interface RagTrace {
  tool_used?: boolean;
  tool_name?: string;
  query?: string;
  expanded_query?: string;
  step_back_question?: string;
  step_back_answer?: string;
  expansion_type?: string;
  hypothetical_doc?: string;
  retrieval_stage?: string;
  grade_score?: string;
  grade_route?: string;
  grade_skipped?: boolean;
  rewrite_needed?: boolean;
  rewrite_strategy?: string;
  rewrite_query?: string;
  rerank_enabled?: boolean;
  rerank_applied?: boolean;
  rerank_model?: string;
  rerank_endpoint?: string;
  rerank_error?: string;
  rerank_min_score?: number;
  retrieval_mode?: string;
  retrieval_pipeline?: string;
  candidate_k?: number;
  candidate_k_source?: string;
  candidate_k_config_error?: string;
  retrieval_candidate_multiplier?: number;
  retrieval_top_k?: number;
  leaf_retrieve_level?: number;
  recall_count?: number;
  post_merge_candidate_count?: number;
  candidate_count?: number;
  auto_merge_enabled?: boolean;
  auto_merge_applied?: boolean;
  auto_merge_threshold?: number;
  auto_merge_replaced_chunks?: number;
  auto_merge_steps?: number;
  post_rerank_count?: number;
  post_threshold_count?: number;
  retrieval_empty?: boolean;
  // v2.0 complexity routing fields
  complexity?: string;
  complexity_reason?: string;
  sub_questions?: string[];
  sub_agent_count?: number;
  synthesis_merged_count?: number;
  sub_traces?: RagTrace[];
  retrieved_chunks?: RetrievedChunk[];
  initial_retrieved_chunks?: RetrievedChunk[];
  expanded_retrieved_chunks?: RetrievedChunk[];
}

export interface RagStep {
  icon?: string;
  label?: string;
  detail?: string;
  group?: string;
  key?: string;
  status?: string;
  percent?: number;
  message?: string;
}

export interface GroupedRagSteps {
  [group: string]: RagStep[];
}

export interface WebSource {
  title: string;
  url: string;
  content: string;
}

export interface WebSources {
  query: string;
  sources: WebSource[];
}

export interface Message {
  text: string;
  isUser: boolean;
  isThinking?: boolean;
  ragTrace?: RagTrace | null;
  ragSteps?: RagStep[];
  _groupedSteps?: GroupedRagSteps | null;
  webSources?: WebSources | null;
}

export interface ChatSession {
  session_id: string;
  title: string;
  message_count: number;
  updated_at: string;
}

// SSE event types
export interface SSEContentEvent {
  type: 'content';
  content: string;
}

export interface SSETraceEvent {
  type: 'trace';
  rag_trace: RagTrace;
}

export interface SSEWebSourcesEvent {
  type: 'web_sources';
  web_sources: WebSources;
}

export interface SSERagStepEvent {
  type: 'rag_step';
  step: RagStep;
}

export interface SSESessionTitleEvent {
  type: 'session_title';
  title: string;
}

export interface SSEErrorEvent {
  type: 'error';
  content: string;
}

export type SSEEvent =
  | SSEContentEvent
  | SSETraceEvent
  | SSEWebSourcesEvent
  | SSERagStepEvent
  | SSESessionTitleEvent
  | SSEErrorEvent;

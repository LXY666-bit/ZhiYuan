import api, { getPublicError } from '@/utils/api';

export type DataQaStatus = 'pending' | 'running' | 'completed' | 'failed';
export type DataQaChartType = 'bar' | 'line' | 'pie' | 'none';

export interface DataQaFieldRationale {
  name: string;
  comment: string;
}

export interface DataQaTableRationale {
  name: string;
  comment: string;
  reason: string;
  score: number;
  fields: DataQaFieldRationale[];
}

export interface DataQaChart {
  chart_type: DataQaChartType;
  label_field: string;
  value_field: string;
  title?: string;
  source?: 'rules' | 'llm';
  recommendation_error?: string | null;
}

export interface DataQaResult {
  sql: string;
  tables: DataQaTableRationale[];
  columns: string[];
  rows: unknown[][];
  row_count: number;
  truncated: boolean;
  chart: DataQaChart;
  analysis: string | null;
}

export interface DataQaQuery {
  id: string;
  question: string;
  status: DataQaStatus;
  run_id: string | null;
  error_code: string | null;
  version: number;
  created_at: string;
  updated_at: string;
  result: DataQaResult | null;
}

export interface DataQaSemanticColumn {
  column_name: string;
  data_type: string;
  sensitive: boolean;
  description: string;
  aliases: string[];
}

export interface DataQaSemanticTable {
  schema_name: string;
  table_name: string;
  description: string;
  aliases: string[];
  columns: DataQaSemanticColumn[];
}

export interface DataQaSemanticSchema {
  fingerprint: string;
  tables: DataQaSemanticTable[];
}

export interface DataQaSemanticMetadataInput {
  schema_name: string;
  table_name: string;
  column_name: string;
  description: string;
  aliases: string[];
}

async function request<T>(pending: Promise<{ data: T }>): Promise<T> {
  try {
    return (await pending).data;
  } catch (error) {
    throw getPublicError(error);
  }
}

const queryPath = (queryId: string) => `/v1/dataqa/queries/${encodeURIComponent(queryId)}`;

export function listDataQaQueries(signal?: AbortSignal): Promise<DataQaQuery[]> {
  return request(api.get<{ queries: DataQaQuery[] }>('/v1/dataqa/queries', { signal })).then(
    (response) => response.queries
  );
}

export function createDataQaQuery(question: string, idempotencyKey: string): Promise<DataQaQuery> {
  return request(
    api.post<DataQaQuery>('/v1/dataqa/queries', {
      question,
      idempotency_key: idempotencyKey,
    })
  );
}

export function getDataQaQuery(queryId: string, signal?: AbortSignal): Promise<DataQaQuery> {
  return request(api.get<DataQaQuery>(queryPath(queryId), { signal }));
}

export function deleteDataQaQuery(queryId: string): Promise<void> {
  return request(api.delete<void>(queryPath(queryId)));
}

export function createDataQaAnalysis(
  queryId: string,
  idempotencyKey: string
): Promise<DataQaQuery> {
  return request(
    api.post<DataQaQuery>(`${queryPath(queryId)}/analysis`, {
      idempotency_key: idempotencyKey,
    })
  );
}

export function getDataQaSemanticSchema(signal?: AbortSignal): Promise<DataQaSemanticSchema> {
  return request(api.get<DataQaSemanticSchema>('/v1/dataqa/semantic-schema', { signal }));
}

export function saveDataQaSemanticMetadata(
  input: DataQaSemanticMetadataInput
): Promise<DataQaSemanticSchema> {
  return request(api.put<DataQaSemanticSchema>('/v1/dataqa/semantic-schema/metadata', input));
}

export interface DocumentItem {
  filename: string;
  file_type: string;
  chunk_count: number;
  uploaded_at?: string;
}

export interface UploadStep {
  key: string;
  label: string;
  percent: number;
  status: 'pending' | 'running' | 'completed' | 'failed';
  message: string;
}

export interface UploadJob {
  job_id: string;
  filename?: string;
  status: string;
  message: string;
  steps: UploadStep[];
  current_step?: string;
  total_chunks?: number;
  processed_chunks?: number;
  error?: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface DeleteStep {
  key: string;
  label: string;
  percent: number;
  status: 'pending' | 'running' | 'completed' | 'failed';
  message: string;
}

export interface DeleteJob {
  job_id: string;
  filename?: string;
  status: string;
  message: string;
  steps: DeleteStep[];
}

export interface ActiveDeleteJob {
  jobId?: string;
  status: string;
  message: string;
  collapsed: boolean;
  steps: DeleteStep[];
}

export interface BatchFile {
  file: File;
  status: 'pending' | 'uploading' | 'running' | 'completed' | 'failed' | 'cancelled';
  jobId: string;
  message: string;
  steps: UploadStep[];
  collapsed: boolean;
  xhr: XMLHttpRequest | null;
  pollTimer: ReturnType<typeof setInterval> | null;
}

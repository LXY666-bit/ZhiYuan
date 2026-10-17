// @vitest-environment jsdom
import { expect, it } from 'vitest';
import { referenceSummary } from './referenceSummary';
import type { RetrievedChunk } from '@/types/chat';

it('counts only rendered valid citations, separately from retrievals and documents', () => {
  const chunks = Array.from({ length: 8 }, (_, i) => ({
    document_id: 'manual',
    chunk_id: String(i),
  })) as RetrievedChunk[];
  expect(referenceSummary('事实 [1, 4]。再次 [1]。无效 [99]。代码 `[2]`。', chunks)).toBe(
    '检索 8 个片段 · 引用 2 个片段（1 份文档）'
  );
  expect(referenceSummary('没有引用', chunks)).toBe('检索 8 个片段 · 引用 0 个片段（0 份文档）');
});

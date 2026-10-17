import type { RetrievedChunk } from '@/types/chat';
import { parseMarkdown } from './markdown';

export function referenceSummary(text: string, chunks: RetrievedChunk[]): string {
  const template = document.createElement('template');
  template.innerHTML = parseMarkdown(text, 0);
  const cited = new Set(
    [...template.content.querySelectorAll<HTMLElement>('.cite-ref')]
      .map((element) => Number(element.dataset.chunkIndex))
      .filter((index) => Number.isInteger(index) && index > 0 && index <= chunks.length)
  );
  const documents = new Set(
    [...cited].map((index) => chunks[index - 1]!.document_id).filter(Boolean)
  );
  return `检索 ${chunks.length} 个片段 · 引用 ${cited.size} 个片段（${documents.size} 份文档）`;
}

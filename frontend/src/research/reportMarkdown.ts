import { parseMarkdown } from '@/utils/markdown';

export function renderResearchMarkdown(markdown: string, citations: Set<string>): string {
  const document = new DOMParser().parseFromString(parseMarkdown(markdown), 'text/html');
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const nodes: Text[] = [];
  while (walker.nextNode()) {
    if (!walker.currentNode.parentElement?.closest('a, code, pre, button')) {
      nodes.push(walker.currentNode as Text);
    }
  }
  for (const node of nodes) {
    const text = node.textContent || '';
    const fragment = document.createDocumentFragment();
    let position = 0;
    let replaced = false;
    for (const match of text.matchAll(/\[(E\d+)\]/g)) {
      if (!citations.has(match[1]!)) continue;
      fragment.append(text.slice(position, match.index));
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'research-citation';
      button.dataset.citation = match[1];
      button.setAttribute('aria-label', `查看证据 ${match[1]}`);
      button.textContent = match[0];
      fragment.append(button);
      position = match.index! + match[0].length;
      replaced = true;
    }
    if (replaced) {
      fragment.append(text.slice(position));
      node.replaceWith(fragment);
    }
  }
  return document.body.innerHTML;
}

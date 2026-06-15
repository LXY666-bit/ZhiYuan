import { marked } from 'marked';
import hljs from 'highlight.js';

const renderer = new marked.Renderer();

// eslint-disable-next-line @typescript-eslint/no-explicit-any
(renderer as any).code = function (code: string, lang?: string): string {
  const language = lang && hljs.getLanguage(lang) ? lang : 'plaintext';
  const highlighted = hljs.highlight(code, { language }).value;
  return `<pre><code class="hljs language-${language}">${highlighted}</code></pre>`;
};

marked.use({
  renderer,
  breaks: true,
  gfm: true,
});

export function parseMarkdown(text: string): string {
  return marked.parse(text || '') as string;
}

export function escapeHtml(text: string): string {
  const div = document.createElement('div');
  div.textContent = text || '';
  return div.innerHTML;
}

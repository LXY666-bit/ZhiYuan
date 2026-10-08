// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import { renderResearchMarkdown } from './reportMarkdown';

describe('research report citations', () => {
  it('makes persisted citations interactive while leaving code, links and unknown IDs alone', () => {
    const html = renderResearchMarkdown(
      '事实 [E1]，未知 [E999]。\n\n`[E1]`\n\n[原文 [E1]](https://example.com)\n\n<script>alert(1)</script>',
      new Set(['E1'])
    );
    const document = new DOMParser().parseFromString(html, 'text/html');
    expect(document.querySelectorAll('button[data-citation]')).toHaveLength(1);
    expect(document.querySelector('button')?.textContent).toBe('[E1]');
    expect(document.querySelector('code')?.textContent).toBe('[E1]');
    expect(document.querySelector('a button')).toBeNull();
    expect(document.querySelector('[data-citation="E999"]')).toBeNull();
    expect(document.querySelector('script')).toBeNull();
  });
});

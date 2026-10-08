// @vitest-environment jsdom

import { afterEach, describe, expect, it } from 'vitest';
import { trapDialogFocus } from './dialogFocus';

afterEach(() => document.body.replaceChildren());

function dialog(markup: string): HTMLElement {
  const element = document.createElement('section');
  element.tabIndex = -1;
  element.innerHTML = markup;
  document.body.append(element);
  return element;
}

function tab(shiftKey = false): KeyboardEvent {
  return new KeyboardEvent('keydown', { key: 'Tab', shiftKey, cancelable: true });
}

describe('dialog keyboard focus', () => {
  it('wraps forward and backward while excluding disabled buttons', () => {
    const element = dialog(
      '<button>First</button><button>Last</button><button disabled>Skip</button>'
    );
    const [first, last] = element.querySelectorAll<HTMLButtonElement>('button');
    last.focus();
    const forward = tab();
    trapDialogFocus(forward, element);
    expect(document.activeElement).toBe(first);
    expect(forward.defaultPrevented).toBe(true);
    const backward = tab(true);
    trapDialogFocus(backward, element);
    expect(document.activeElement).toBe(last);
    expect(backward.defaultPrevented).toBe(true);
  });

  it('allows normal Tab navigation between interior controls', () => {
    const element = dialog('<button>First</button><button>Middle</button><button>Last</button>');
    element.querySelectorAll<HTMLButtonElement>('button')[1].focus();
    const event = tab();
    trapDialogFocus(event, element);
    expect(event.defaultPrevented).toBe(false);
  });

  it('includes inputs when the dialog provides its input selector', () => {
    const element = dialog('<input><button>Last</button>');
    element.querySelector<HTMLButtonElement>('button')!.focus();
    trapDialogFocus(tab(), element, 'input, button:not(:disabled)');
    expect(document.activeElement).toBe(element.querySelector('input'));
  });

  it('keeps the artifact dialog focusable even without interactive children', () => {
    const element = dialog('<p>Preview</p>');
    const event = tab();
    trapDialogFocus(event, element, 'button', true);
    expect(event.defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(element);
  });

  it('leaves absent and empty dialogs alone unless fallback focus is requested', () => {
    const event = tab();
    trapDialogFocus(event, null);
    trapDialogFocus(event, dialog(''));
    expect(event.defaultPrevented).toBe(false);
  });
});

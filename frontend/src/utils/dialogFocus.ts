export function trapDialogFocus(
  event: KeyboardEvent,
  dialog: HTMLElement | null,
  selector = 'button:not(:disabled), [tabindex]:not([tabindex="-1"])',
  focusEmpty = false
): void {
  if (!dialog) return;
  const focusable = dialog.querySelectorAll<HTMLElement>(selector);
  if (!focusable.length) {
    if (focusEmpty) {
      event.preventDefault();
      dialog.focus();
    }
    return;
  }
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

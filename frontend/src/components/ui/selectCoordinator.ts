const closeHandlers = new Map<string, () => void>();
let activeSelectId: string | null = null;

export function notifySelectOpened(selectId: string, close: () => void): void {
  if (activeSelectId && activeSelectId !== selectId) {
    closeHandlers.get(activeSelectId)?.();
  }
  activeSelectId = selectId;
  closeHandlers.set(selectId, close);
}

export function notifySelectClosed(selectId: string): void {
  if (activeSelectId === selectId) {
    activeSelectId = null;
  }
  closeHandlers.delete(selectId);
}

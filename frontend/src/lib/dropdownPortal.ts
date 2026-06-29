/** Shared positioning for portaled dropdown menus (above modals at z-200). */

export const DROPDOWN_MENU_Z_INDEX = 320;

export type DropdownMenuPosition = {
  top: number;
  left: number;
  width: number;
  maxHeight: number;
};

export function computeDropdownMenuPosition(
  trigger: HTMLElement,
  options?: { minWidth?: number; maxHeight?: number }
): DropdownMenuPosition {
  const minWidth = options?.minWidth ?? 160;
  const preferredMaxHeight = options?.maxHeight ?? 320;
  const rect = trigger.getBoundingClientRect();
  const width = Math.max(rect.width, minWidth);
  const margin = 8;

  const spaceBelow = window.innerHeight - rect.bottom - margin;
  const spaceAbove = rect.top - margin;
  const openUp = spaceBelow < 180 && spaceAbove > spaceBelow;
  const maxHeight = Math.max(
    120,
    Math.min(preferredMaxHeight, openUp ? spaceAbove - 4 : spaceBelow - 4)
  );
  const top = openUp ? Math.max(margin, rect.top - maxHeight - 4) : rect.bottom + 4;

  let left = rect.left;
  if (left + width > window.innerWidth - margin) {
    left = Math.max(margin, window.innerWidth - width - margin);
  }

  return { top, left, width, maxHeight };
}

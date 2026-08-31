import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from "react";

const KEEP_HOVER_OPEN_SELECTOR = [
  '[data-testid="menu-settings"]',
  '[data-testid="menu-profile"]',
  '[data-testid="menu-notifications"]',
  ".profile-menu",
  ".global-search-backdrop",
  ".global-search-dialog",
].join(",");

function pointHits(x: number, y: number, el: Element | null) {
  if (!el) return false;
  const rect = el.getBoundingClientRect();
  if (rect.width <= 0 || rect.height <= 0) return false;
  return x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom;
}

export function useUnpinnedSidebarHover(sidebarPinned: boolean, pathname: string) {
  const [sidebarHovered, setSidebarHovered] = useState(false);
  const sidebarRef = useRef<HTMLElement>(null);

  const closeHover = useCallback(() => {
    setSidebarHovered(false);
  }, []);

  useEffect(() => {
    closeHover();
  }, [pathname, closeHover]);

  useEffect(() => {
    if (sidebarPinned) closeHover();
  }, [sidebarPinned, closeHover]);

  useEffect(() => {
    if (sidebarPinned || !sidebarHovered) return;

    const isInsideSidebar = (event: PointerEvent) => {
      const target = event.target;
      if (target instanceof Element && target.closest(KEEP_HOVER_OPEN_SELECTOR)) {
        return true;
      }
      const root = sidebarRef.current;
      if (!root) return false;
      const rail = root.querySelector(".primary-sidebar__rail");
      const flyout = root.querySelector(".primary-sidebar__flyout");
      return (
        pointHits(event.clientX, event.clientY, rail) ||
        pointHits(event.clientX, event.clientY, flyout) ||
        pointHits(event.clientX, event.clientY, root)
      );
    };

    const closeIfOutside = (event: PointerEvent) => {
      if (!isInsideSidebar(event)) closeHover();
    };

    document.addEventListener("pointermove", closeIfOutside, { passive: true });
    document.addEventListener("pointerdown", closeIfOutside, true);
    return () => {
      document.removeEventListener("pointermove", closeIfOutside);
      document.removeEventListener("pointerdown", closeIfOutside, true);
    };
  }, [sidebarHovered, sidebarPinned, closeHover]);

  const onSidebarPointerEnter = () => {
    if (!sidebarPinned) setSidebarHovered(true);
  };

  const onSidebarPointerLeave = (event: ReactPointerEvent<HTMLElement>) => {
    if (sidebarPinned) return;
    const next = event.relatedTarget;
    if (next instanceof Node && sidebarRef.current?.contains(next)) return;
    if (next instanceof Element && next.closest(KEEP_HOVER_OPEN_SELECTOR)) return;
    const root = sidebarRef.current;
    if (root) {
      const rail = root.querySelector(".primary-sidebar__rail");
      const flyout = root.querySelector(".primary-sidebar__flyout");
      if (
        pointHits(event.clientX, event.clientY, rail) ||
        pointHits(event.clientX, event.clientY, flyout) ||
        pointHits(event.clientX, event.clientY, root)
      ) {
        return;
      }
    }
    closeHover();
  };

  return {
    sidebarHovered,
    setSidebarHovered,
    sidebarRef,
    closeHover,
    onSidebarPointerEnter,
    onSidebarPointerLeave,
    showDismiss: !sidebarPinned && sidebarHovered,
  };
}

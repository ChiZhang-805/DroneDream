import {
  type RefObject,
  useCallback,
  useEffect,
  useRef,
} from "react";

const FOCUSABLE_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(", ");

interface ModalFocusOptions {
  open: boolean;
  dialogRef: RefObject<HTMLElement | null>;
  initialFocusRef?: RefObject<HTMLElement | null>;
  onClose: () => void;
}

/** Match the app's DOM-ordered modal portals, excluding hidden/closing dialogs. */
function topmostModal(): HTMLElement | undefined {
  const dialogs = Array.from(
    document.querySelectorAll<HTMLElement>('[role="dialog"][aria-modal="true"]'),
  ).filter(isVisible);
  return dialogs.at(-1);
}

/** Respect hidden/inert ancestors without requiring layout measurements in headless tests. */
function isVisible(element: HTMLElement): boolean {
  for (let current: HTMLElement | null = element; current; current = current.parentElement) {
    if (current.hidden || current.hasAttribute("inert")) return false;
    const style = window.getComputedStyle(current);
    if (style.display === "none" || style.visibility === "hidden" || style.visibility === "collapse") {
      return false;
    }
  }
  return true;
}

/** Use browser tab order, not every matching element: disabled/negative-tabindex controls are skipped. */
function focusableControls(dialog: HTMLElement): HTMLElement[] {
  return Array.from(dialog.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR))
    .filter((element) => element.tabIndex >= 0 && !element.matches(":disabled") && isVisible(element))
    .sort((left, right) => {
      const leftOrder = left.tabIndex > 0 ? left.tabIndex : Infinity;
      const rightOrder = right.tabIndex > 0 ? right.tabIndex : Infinity;
      return leftOrder === rightOrder ? 0 : leftOrder - rightOrder;
    });
}

const scrollOwners = new Set<symbol>();
let overflowBeforeModals = "";

/** A shared lease keeps scrolling locked even when nested dialogs close out of order. */
function acquireScrollLock(): () => void {
  const owner = Symbol("modal-scroll");
  if (scrollOwners.size === 0) overflowBeforeModals = document.body.style.overflow;
  scrollOwners.add(owner);
  document.body.style.overflow = "hidden";
  return () => {
    if (scrollOwners.delete(owner) && scrollOwners.size === 0) {
      document.body.style.overflow = overflowBeforeModals;
    }
  };
}

/** Trap keyboard focus, own one scroll lease, and restore a still-valid trigger on close. */
export function useModalFocus({
  open,
  dialogRef,
  initialFocusRef,
  onClose,
}: ModalFocusOptions): () => void {
  const triggerRef = useRef<HTMLElement | null>(null);
  const closeActionRef = useRef(onClose);
  const focusGeneration = useRef(0);
  closeActionRef.current = onClose;

  const captureTrigger = useCallback(() => {
    triggerRef.current = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
  }, []);

  useEffect(() => {
    if (!open) return;
    focusGeneration.current += 1;
    if (!triggerRef.current && document.activeElement instanceof HTMLElement) {
      triggerRef.current = document.activeElement;
    }
    const releaseScrollLock = acquireScrollLock();
    const focusFrame = window.requestAnimationFrame(() => {
      const dialog = dialogRef.current;
      if (!dialog || topmostModal() !== dialog) return;
      const controls = focusableControls(dialog);
      const initial = initialFocusRef?.current;
      // A caller may intentionally focus a visible heading with tabindex=-1;
      // it need not belong to the sequential Tab order.
      (initial && dialog.contains(initial) && !initial.matches(":disabled") && isVisible(initial)
        ? initial : controls[0] ?? dialog).focus({
        preventScroll: true,
      });
    });

    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      const dialog = dialogRef.current;
      if (event.defaultPrevented || !dialog || topmostModal() !== dialog) return;
      if (event.key === "Escape") {
        event.preventDefault();
        closeActionRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = focusableControls(dialog);
      const first = focusable[0];
      const last = focusable.at(-1);
      if (!first || !last) {
        event.preventDefault();
        dialog.focus({ preventScroll: true });
        return;
      }
      if (!dialog.contains(document.activeElement) || document.activeElement === dialog) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      } else if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", onKeyDown);

    return () => {
      window.cancelAnimationFrame(focusFrame);
      releaseScrollLock();
      window.removeEventListener("keydown", onKeyDown);
      const trigger = triggerRef.current;
      triggerRef.current = null;
      const returnGeneration = ++focusGeneration.current;
      if (trigger?.isConnected) {
        window.requestAnimationFrame(() => {
          // A reopened dialog or another still-open modal owns focus now. Late
          // cleanup must not send the keyboard behind it to an unrelated trigger.
          const activeDialog = topmostModal();
          if (returnGeneration === focusGeneration.current && trigger.isConnected &&
              (!activeDialog || activeDialog.contains(trigger))) {
            trigger.focus({ preventScroll: true });
          }
        });
      }
    };
  }, [dialogRef, initialFocusRef, open]);

  return captureTrigger;
}

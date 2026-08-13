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

function isTopmostModal(dialog: HTMLElement): boolean {
  const dialogs = Array.from(
    document.querySelectorAll<HTMLElement>('[role="dialog"][aria-modal="true"]'),
  );
  return dialogs.at(-1) === dialog;
}

export function useModalFocus({
  open,
  dialogRef,
  initialFocusRef,
  onClose,
}: ModalFocusOptions): () => void {
  const triggerRef = useRef<HTMLElement | null>(null);
  const closeActionRef = useRef(onClose);
  closeActionRef.current = onClose;

  const captureTrigger = useCallback(() => {
    triggerRef.current = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
  }, []);

  useEffect(() => {
    if (!open) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const focusFrame = window.requestAnimationFrame(() => {
      const dialog = dialogRef.current;
      if (!dialog) return;
      const firstFocusable = dialog.querySelector<HTMLElement>(FOCUSABLE_SELECTOR);
      (initialFocusRef?.current ?? firstFocusable ?? dialog).focus({
        preventScroll: true,
      });
    });

    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      const dialog = dialogRef.current;
      if (!dialog || !isTopmostModal(dialog)) return;
      if (event.key === "Escape") {
        event.preventDefault();
        closeActionRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = Array.from(
        dialog.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
      );
      const first = focusable[0];
      const last = focusable.at(-1);
      if (!first || !last) {
        event.preventDefault();
        dialog.focus({ preventScroll: true });
        return;
      }
      if (event.shiftKey && document.activeElement === first) {
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
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", onKeyDown);
      const trigger = triggerRef.current;
      triggerRef.current = null;
      if (trigger?.isConnected) {
        window.requestAnimationFrame(() => {
          if (trigger.isConnected) trigger.focus({ preventScroll: true });
        });
      }
    };
  }, [dialogRef, initialFocusRef, open]);

  return captureTrigger;
}

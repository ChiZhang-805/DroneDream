/** Exercise shared website/app focus ownership, not just each modal in isolation. */
import { useRef } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useModalFocus } from "../hooks/useModalFocus";
import { useModalFocus as useSiteModalFocus } from "../site/useModalFocus";

function Dialog({ open, name, onClose = () => undefined }: {
  open: boolean; name: string; onClose?: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useModalFocus({ open, dialogRef: ref, onClose });
  return open ? (
    <div ref={ref} role="dialog" aria-modal="true" aria-label={name} tabIndex={-1}>
      <button style={{ display: "none" }}>Hidden {name}</button>
      <button disabled tabIndex={0}>Disabled {name}</button>
      <button>First {name}</button>
      <button>Last {name}</button>
    </div>
  ) : null;
}

beforeEach(() => { vi.useFakeTimers(); document.body.style.overflow = "auto"; });
afterEach(() => { cleanup(); vi.runOnlyPendingTimers(); vi.useRealTimers(); document.body.style.overflow = ""; });

describe("modal focus and scroll ownership", () => {
  it("shares one implementation across site and app", () => {
    expect(useSiteModalFocus).toBe(useModalFocus);
  });

  it("retains the lock when the lower dialog closes first and restores the original overflow last", () => {
    const { rerender } = render(<><Dialog open name="lower" /><Dialog open name="upper" /></>);
    expect(document.body.style.overflow).toBe("hidden");
    rerender(<><Dialog open={false} name="lower" /><Dialog open name="upper" /></>);
    expect(document.body.style.overflow).toBe("hidden");
    rerender(<><Dialog open={false} name="lower" /><Dialog open={false} name="upper" /></>);
    expect(document.body.style.overflow).toBe("auto");
  });

  it("initially focuses an enabled visible control in the topmost dialog", () => {
    render(<><Dialog open name="lower" /><Dialog open name="upper" /></>);
    vi.runOnlyPendingTimers();
    expect(screen.getByRole("button", { name: "First upper" })).toHaveFocus();
  });

  it("recovers escaped focus and wraps around visible enabled controls", () => {
    render(<><button>Outside</button><Dialog open name="active" /></>);
    screen.getByRole("button", { name: "Outside" }).focus();
    fireEvent.keyDown(window, { key: "Tab" });
    expect(screen.getByRole("button", { name: "First active" })).toHaveFocus();
    fireEvent.keyDown(window, { key: "Tab", shiftKey: true });
    expect(screen.getByRole("button", { name: "Last active" })).toHaveFocus();
    fireEvent.keyDown(window, { key: "Tab" });
    expect(screen.getByRole("button", { name: "First active" })).toHaveFocus();
  });

  it("only lets the topmost dialog handle Escape", () => {
    const lower = vi.fn(), upper = vi.fn();
    render(<><Dialog open name="lower" onClose={lower} /><Dialog open name="upper" onClose={upper} /></>);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(upper).toHaveBeenCalledOnce();
    expect(lower).not.toHaveBeenCalled();
  });
});

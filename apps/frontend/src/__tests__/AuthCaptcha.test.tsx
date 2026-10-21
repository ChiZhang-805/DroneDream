import { act, fireEvent, render, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AuthCaptcha } from "../features/auth/AuthCaptcha";

const SCRIPT_ID = "drone-dream-turnstile-script";

afterEach(() => {
  vi.useRealTimers();
  delete window.turnstile;
  document.getElementById(SCRIPT_ID)?.remove();
});

describe("AuthCaptcha", () => {
  it("times out a stalled script so a later mount can retry", async () => {
    vi.useFakeTimers();
    const page = render(<AuthCaptcha siteKey="site-key" onTokenChange={vi.fn()} />);
    const stalled = document.getElementById(SCRIPT_ID);
    expect(stalled).toBeInstanceOf(HTMLScriptElement);
    await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
    expect(document.getElementById(SCRIPT_ID)).toBeNull();
    page.unmount();
    const retry = render(<AuthCaptcha siteKey="site-key" onTokenChange={vi.fn()} />);
    expect(document.getElementById(SCRIPT_ID)).not.toBe(stalled);
    await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
    retry.unmount();
  });

  it("replaces a failed script and preserves the widget lifecycle", async () => {
    const failedTokenChange = vi.fn();
    const failedRender = render(
      <AuthCaptcha siteKey="site-key" onTokenChange={failedTokenChange} />,
    );
    const failedScript = document.getElementById(SCRIPT_ID);
    expect(failedScript).toBeInstanceOf(HTMLScriptElement);

    fireEvent.error(failedScript as HTMLScriptElement);
    await waitFor(() => expect(document.getElementById(SCRIPT_ID)).toBeNull());
    expect(failedTokenChange).toHaveBeenLastCalledWith(null);
    failedRender.unmount();

    const remove = vi.fn();
    let options: {
      callback: (token: string) => void;
      "error-callback": () => void;
      "expired-callback": () => void;
      "timeout-callback": () => void;
    } | null = null;
    const renderWidget = vi.fn((_container, nextOptions) => {
      options = nextOptions;
      return "widget-1";
    });
    const tokenChange = vi.fn();
    const page = render(
      <AuthCaptcha siteKey="site-key" onTokenChange={tokenChange} />,
    );
    const retryScript = document.getElementById(SCRIPT_ID);
    expect(retryScript).toBeInstanceOf(HTMLScriptElement);
    expect(retryScript).not.toBe(failedScript);

    window.turnstile = { render: renderWidget, remove };
    fireEvent.load(retryScript as HTMLScriptElement);
    await waitFor(() => expect(renderWidget).toHaveBeenCalledOnce());

    expect(options).not.toBeNull();
    options!.callback("verified-token");
    expect(tokenChange).toHaveBeenLastCalledWith("verified-token");
    options!["error-callback"]();
    options!["expired-callback"]();
    options!["timeout-callback"]();
    expect(tokenChange).toHaveBeenLastCalledWith(null);

    page.unmount();
    expect(remove).toHaveBeenCalledWith("widget-1");
    expect(tokenChange).toHaveBeenLastCalledWith(null);
  });
});

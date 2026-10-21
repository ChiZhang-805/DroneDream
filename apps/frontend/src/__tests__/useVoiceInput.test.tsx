import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useVoiceInput } from "../features/experiment/useVoiceInput";

const originalMediaDevicesDescriptor = Object.getOwnPropertyDescriptor(
  navigator,
  "mediaDevices",
);

describe("useVoiceInput", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    delete (window as typeof window & { SpeechRecognition?: unknown })
      .SpeechRecognition;
    if (originalMediaDevicesDescriptor) {
      Object.defineProperty(
        navigator,
        "mediaDevices",
        originalMediaDevicesDescriptor,
      );
    } else {
      Reflect.deleteProperty(navigator, "mediaDevices");
    }
  });

  it("does not start recognition when the page closes during permission", async () => {
    let resolvePermission: ((stream: MediaStream) => void) | null = null;
    const permission = new Promise<MediaStream>((resolve) => {
      resolvePermission = resolve;
    });
    const stopTrack = vi.fn();
    const getUserMedia = vi.fn(() => permission);
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia },
    });
    const recognitionStart = vi.fn();
    const Recognition = vi.fn(function RecognitionMock() {
      return {
        lang: "",
        continuous: false,
        interimResults: false,
        maxAlternatives: 1,
        onresult: null,
        onerror: null,
        onend: null,
        start: recognitionStart,
        stop: vi.fn(),
        abort: vi.fn(),
      };
    });
    (
      window as typeof window & {
        SpeechRecognition?: typeof Recognition;
      }
    ).SpeechRecognition = Recognition;

    const { result, unmount } = renderHook(() =>
      useVoiceInput({ locale: "en", onTranscript: vi.fn() })
    );
    let startPromise: Promise<void> | undefined;
    act(() => {
      startPromise = result.current.start();
    });
    expect(result.current.state).toBe("requesting");
    unmount();

    await act(async () => {
      resolvePermission?.({
        getTracks: () => [{ stop: stopTrack }],
      } as unknown as MediaStream);
      await startPromise;
    });

    expect(stopTrack).toHaveBeenCalledTimes(1);
    expect(Recognition).not.toHaveBeenCalled();
    expect(recognitionStart).not.toHaveBeenCalled();
  });

  it("does not start recognition after Stop cancels a pending permission request", async () => {
    let resolvePermission: ((stream: MediaStream) => void) | null = null;
    const permission = new Promise<MediaStream>((resolve) => {
      resolvePermission = resolve;
    });
    const stopTrack = vi.fn();
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia: vi.fn(() => permission) },
    });
    const Recognition = vi.fn(function RecognitionMock() {
      return {
        lang: "",
        continuous: false,
        interimResults: false,
        maxAlternatives: 1,
        onresult: null,
        onerror: null,
        onend: null,
        start: vi.fn(),
        stop: vi.fn(),
        abort: vi.fn(),
      };
    });
    (
      window as typeof window & {
        SpeechRecognition?: typeof Recognition;
      }
    ).SpeechRecognition = Recognition;

    const { result } = renderHook(() =>
      useVoiceInput({ locale: "en", onTranscript: vi.fn() })
    );
    let startPromise: Promise<void> | undefined;
    act(() => {
      startPromise = result.current.start();
    });
    act(() => {
      result.current.stop();
    });

    await act(async () => {
      resolvePermission?.({
        getTracks: () => [{ stop: stopTrack }],
      } as unknown as MediaStream);
      await startPromise;
    });

    expect(result.current.state).toBe("idle");
    expect(stopTrack).toHaveBeenCalledTimes(1);
    expect(Recognition).not.toHaveBeenCalled();
  });
});

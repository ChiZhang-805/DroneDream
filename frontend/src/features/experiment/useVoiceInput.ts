import { useCallback, useEffect, useRef, useState } from "react";

type VoiceInputState = "idle" | "requesting" | "listening" | "error";

interface SpeechRecognitionResultLike {
  0?: { transcript?: string };
  isFinal?: boolean;
}

interface SpeechRecognitionEventLike {
  results: ArrayLike<SpeechRecognitionResultLike>;
  resultIndex: number;
}

interface SpeechRecognitionErrorLike {
  error?: string;
}

interface SpeechRecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onerror: ((event: SpeechRecognitionErrorLike) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
  abort: () => void;
}

type SpeechRecognitionConstructor = new () => SpeechRecognitionLike;
const MAX_RECOGNITION_DURATION_MS = 60_000;

function recognitionConstructor(): SpeechRecognitionConstructor | null {
  const candidate = window as typeof window & {
    SpeechRecognition?: SpeechRecognitionConstructor;
    webkitSpeechRecognition?: SpeechRecognitionConstructor;
  };
  return candidate.SpeechRecognition ?? candidate.webkitSpeechRecognition ?? null;
}

function voiceErrorMessage(error: unknown): string {
  if (error instanceof DOMException && error.name === "NotAllowedError") {
    return "microphone_permission_denied";
  }
  if (error instanceof DOMException && error.name === "NotFoundError") {
    return "microphone_not_found";
  }
  return "microphone_unavailable";
}

function recognitionErrorMessage(error: string | undefined): string {
  if (error === "not-allowed" || error === "service-not-allowed") {
    return "microphone_permission_denied";
  }
  if (error === "audio-capture") return "microphone_not_found";
  return error || "speech_recognition_failed";
}

export function useVoiceInput({
  locale,
  onTranscript,
}: {
  locale: "en" | "zh-CN";
  onTranscript: (transcript: string) => void;
}) {
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const timeoutRef = useRef<number | null>(null);
  const [state, setState] = useState<VoiceInputState>("idle");
  const [error, setError] = useState<string | null>(null);
  const supported =
    typeof window !== "undefined" &&
    typeof navigator !== "undefined" &&
    Boolean(navigator.mediaDevices?.getUserMedia) &&
    recognitionConstructor() !== null;

  const clearRecognitionTimeout = useCallback(() => {
    if (timeoutRef.current !== null) {
      window.clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
  }, []);

  const stop = useCallback(() => {
    clearRecognitionTimeout();
    recognitionRef.current?.stop();
    recognitionRef.current = null;
    setState("idle");
  }, [clearRecognitionTimeout]);

  const start = useCallback(async () => {
    if (state === "requesting" || state === "listening") return;
    const Recognition = recognitionConstructor();
    if (!Recognition || !navigator.mediaDevices?.getUserMedia) {
      setError("voice_not_supported");
      setState("error");
      return;
    }
    setState("requesting");
    setError(null);
    try {
      // Permission is requested only inside this user-initiated callback.
      // This probe is never retained; SpeechRecognition owns its own stream.
      const permissionStream = await navigator.mediaDevices.getUserMedia({
        audio: true,
      });
      permissionStream.getTracks().forEach((track) => track.stop());

      const recognition = new Recognition();
      recognitionRef.current = recognition;
      recognition.lang = locale === "zh-CN" ? "zh-CN" : "en-US";
      recognition.continuous = false;
      recognition.interimResults = false;
      recognition.maxAlternatives = 1;
      recognition.onresult = (event) => {
        let transcript = "";
        for (let index = event.resultIndex; index < event.results.length; index += 1) {
          const result = event.results[index];
          if (result?.isFinal !== false) {
            transcript += result?.[0]?.transcript ?? "";
          }
        }
        const normalized = transcript.trim();
        if (normalized) onTranscript(normalized);
      };
      recognition.onerror = (event) => {
        clearRecognitionTimeout();
        setError(recognitionErrorMessage(event.error));
        setState("error");
        recognitionRef.current = null;
      };
      recognition.onend = () => {
        clearRecognitionTimeout();
        recognitionRef.current = null;
        setState((current) => (current === "error" ? current : "idle"));
      };
      recognition.start();
      timeoutRef.current = window.setTimeout(() => {
        recognitionRef.current?.stop();
      }, MAX_RECOGNITION_DURATION_MS);
      setState("listening");
    } catch (reason) {
      clearRecognitionTimeout();
      setError(voiceErrorMessage(reason));
      setState("error");
      recognitionRef.current = null;
    }
  }, [clearRecognitionTimeout, locale, onTranscript, state]);

  useEffect(
    () => () => {
      clearRecognitionTimeout();
      recognitionRef.current?.abort();
      recognitionRef.current = null;
    },
    [clearRecognitionTimeout],
  );

  return {
    state,
    error,
    supported,
    start,
    stop,
    clearError: () => {
      setError(null);
      setState("idle");
    },
  };
}

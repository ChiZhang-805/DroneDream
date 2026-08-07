import { useEffect, useState } from "react";

import {
  appReducedMotionEnabled,
  REDUCE_MOTION_CHANGE_EVENT,
} from "../desktop/uiMotionPreferences";

const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";

function readReducedMotionPreference() {
  if (typeof window === "undefined") return false;
  return appReducedMotionEnabled()
    || (typeof window.matchMedia === "function"
      && window.matchMedia(REDUCED_MOTION_QUERY).matches);
}

/** Keeps animation-heavy views in sync with the operating-system motion setting. */
export function usePrefersReducedMotion() {
  const [prefersReducedMotion, setPrefersReducedMotion] = useState(
    readReducedMotionPreference,
  );

  useEffect(() => {
    const mediaQuery = typeof window.matchMedia === "function"
      ? window.matchMedia(REDUCED_MOTION_QUERY)
      : null;
    const updateCombinedPreference = () => setPrefersReducedMotion(readReducedMotionPreference());
    updateCombinedPreference();
    window.addEventListener(REDUCE_MOTION_CHANGE_EVENT, updateCombinedPreference);
    if (typeof mediaQuery?.addEventListener === "function") {
      mediaQuery.addEventListener("change", updateCombinedPreference);
      return () => {
        mediaQuery.removeEventListener("change", updateCombinedPreference);
        window.removeEventListener(REDUCE_MOTION_CHANGE_EVENT, updateCombinedPreference);
      };
    }
    mediaQuery?.addListener?.(updateCombinedPreference);
    return () => {
      mediaQuery?.removeListener?.(updateCombinedPreference);
      window.removeEventListener(REDUCE_MOTION_CHANGE_EVENT, updateCombinedPreference);
    };
  }, []);

  return prefersReducedMotion;
}

import { useEffect, useState, useSyncExternalStore } from "react";
import { appReducedMotionEnabled, subscribeToAppReducedMotion } from "../desktop/uiMotionPreferences";

const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";

/** Read only the OS signal here; the explicit in-app signal is combined below. */
function readReducedMotionPreference() {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    ? window.matchMedia(REDUCED_MOTION_QUERY).matches
    : false;
}

/** Either the OS or the user can reduce motion, including requestAnimationFrame-driven scenes. */
export function usePrefersReducedMotion() {
  const [prefersReducedMotion, setPrefersReducedMotion] = useState(
    readReducedMotionPreference,
  );
  const appReducedMotion = useSyncExternalStore(
    subscribeToAppReducedMotion, appReducedMotionEnabled, () => false,
  );

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const mediaQuery = window.matchMedia(REDUCED_MOTION_QUERY);
    const updatePreference = () => setPrefersReducedMotion(mediaQuery.matches);
    updatePreference();
    if (typeof mediaQuery.addEventListener === "function") {
      mediaQuery.addEventListener("change", updatePreference);
      return () => mediaQuery.removeEventListener("change", updatePreference);
    }
    mediaQuery.addListener?.(updatePreference);
    return () => mediaQuery.removeListener?.(updatePreference);
  }, []);

  return prefersReducedMotion || appReducedMotion;
}

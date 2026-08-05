import compactLockup from "../assets/drone-dream-lockup-compact.png";
import primaryLockup from "../assets/drone-dream-lockup-primary.png";
import labDotLockup from "../../../distribution/editions/lab/assets/dronedream-lab-dot-lockup-v2.png";
import type { AppEdition } from "../edition";

export function resolveBrandLockupSource(
  edition: AppEdition,
  variant: "primary" | "compact",
) {
  if (edition === "lab") return labDotLockup;
  return variant === "primary" ? primaryLockup : compactLockup;
}

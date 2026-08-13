import type { HardwareDomainEdition } from "../desktop/bridge";

export const hardwareDomainEdition: HardwareDomainEdition =
  (import.meta.env.VITE_DRONEDREAM_EDITION as string | undefined)?.toLowerCase() === "lab"
    ? "lab"
    : "field";

export const hardwareDomainRuntimeProfile = hardwareDomainEdition === "lab"
  ? "unified-sim-lab" as const
  : "field-lightweight" as const;

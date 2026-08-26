import type { HardwareDomainEdition } from "../desktop/bridge";

const configuredEdition =
  (import.meta.env.VITE_DRONEDREAM_EDITION as string | undefined)?.toLowerCase();

export const hardwareDomainEdition: HardwareDomainEdition = configuredEdition === "lab"
  ? "lab"
  : configuredEdition === "autonomy"
    ? "autonomy"
    : "field";

export const hardwareDomainRuntimeProfile = hardwareDomainEdition === "lab"
  ? "unified-sim-lab" as const
  : hardwareDomainEdition === "autonomy"
    ? "autonomy-full" as const
    : "field-lightweight" as const;

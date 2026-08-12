export const SOFTWARE_EDITION_IDS = [
  "universal",
  "sim",
  "lab",
  "field",
] as const;

export type SoftwareEditionId = (typeof SOFTWARE_EDITION_IDS)[number];

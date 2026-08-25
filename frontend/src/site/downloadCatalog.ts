import autonomyMark from "../../../brand/commercial/autonomy-mark.png";
import fieldMark from "../../../brand/commercial/field-mark.png";
import labMark from "../../../brand/commercial/lab-mark.png";
import simMark from "../../../brand/commercial/sim-mark.png";
import universalMark from "../../../brand/commercial/universal-mark.png";

export type HeaderDownloadId = "universal" | "sim" | "lab" | "field" | "autonomy";

const RELEASE_BASE =
  "https://github.com/ChiZhang-805/DroneDream/releases/download/five-edition-v1.0.0-build-1718";

export const headerDownloadCatalog = [
  {
    id: "universal",
    label: "DroneDream Universal",
    fileName: "DroneDream-Universal_1.0.0_x64-setup.exe",
    sizeBytes: 83_254_673,
    sha256: "5a1dd4db9ede017676ae14ba7c89d636be2a314f817b3a73d8ea857a5ac25ac4",
    mark: universalMark,
  },
  {
    id: "sim",
    label: "DroneDream SIM",
    fileName: "DroneDream-Sim_1.0.0_x64-setup.exe",
    sizeBytes: 82_682_197,
    sha256: "b6e8356562ec22dc3fbfb8536ea909aa7d3b6866eff04f7ff6287f50c666b81a",
    mark: simMark,
  },
  {
    id: "lab",
    label: "DroneDream LAB",
    fileName: "DroneDream-Lab_1.0.0_x64-setup.exe",
    sizeBytes: 83_203_849,
    sha256: "92523737c950373ee31ae6d96c5fe3eaaaffa516ee6e5e71187ddeac3f9c4ec5",
    mark: labMark,
  },
  {
    id: "field",
    label: "DroneDream FIELD",
    fileName: "DroneDream-Field_1.0.0_x64-setup.exe",
    sizeBytes: 82_924_622,
    sha256: "ce2dd4d71d793e385b99b2563b1d0d47cc60d8b65120d9921df00af3bfc6f77c",
    mark: fieldMark,
  },
  {
    id: "autonomy",
    label: "DroneDream AGENT",
    fileName: "DroneDream-Agent_1.0.0_x64-setup.exe",
    sizeBytes: 83_120_585,
    sha256: "a091bb37e512a01cebedadf48dd3bb5e8b28857303219cc107c9fb64a74090fd",
    mark: autonomyMark,
  },
].map((download) => ({
  ...download,
  downloadUrl: `${RELEASE_BASE}/${download.fileName}`,
})) as readonly {
  id: HeaderDownloadId;
  label: string;
  fileName: string;
  sizeBytes: number;
  sha256: string;
  mark: string;
  downloadUrl: string;
}[];

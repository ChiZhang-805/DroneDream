import autonomyMark from "../../../brand/icons/agent-mark.png";
import fieldMark from "../../../brand/icons/field-mark.png";
import labMark from "../../../brand/icons/lab-mark.png";
import simMark from "../../../brand/icons/sim-mark.png";
import universalMark from "../../../brand/icons/universal-mark.png";

export type HeaderDownloadId = "universal" | "sim" | "lab" | "field" | "autonomy";

const RELEASE_BASE =
  "https://github.com/ChiZhang-805/DroneDream/releases/download/five-edition-v1.0.0-build-1813";

export const headerDownloadCatalog = [
  {
    id: "universal",
    label: "DroneDream Universal",
    fileName: "DroneDream-Universal_1.0.0_x64-setup.exe",
    sizeBytes: 83_125_741,
    sha256: "b6cef8e98d940891c7d06f1e4c80d1d2a84858f3941abd7ec6ceb7f30ce9d34f",
    mark: universalMark,
  },
  {
    id: "sim",
    label: "DroneDream SIM",
    fileName: "DroneDream-Sim_1.0.0_x64-setup.exe",
    sizeBytes: 82_566_552,
    sha256: "891ac5e6d2d709e8a7f7ad4ae67d6da74a02b6d278c00774b18fd08c7de11f19",
    mark: simMark,
  },
  {
    id: "lab",
    label: "DroneDream LAB",
    fileName: "DroneDream-Lab_1.0.0_x64-setup.exe",
    sizeBytes: 83_088_000,
    sha256: "10e93d53ec40fc7c04b5a65b9e417ef8fca841b464fced59e75f9163915c2c54",
    mark: labMark,
  },
  {
    id: "field",
    label: "DroneDream FIELD",
    fileName: "DroneDream-Field_1.0.0_x64-setup.exe",
    sizeBytes: 82_797_618,
    sha256: "3245132f53ea577bf7b8d2d294249b5a6402a4dea25a892a3a10573db376ed64",
    mark: fieldMark,
  },
  {
    id: "autonomy",
    label: "DroneDream AGENT",
    fileName: "DroneDream-Agent_1.0.0_x64-setup.exe",
    sizeBytes: 82_988_181,
    sha256: "637918f87ca9e926a6866271890c9d0962cd0edcf0a6251d9658e64a732af773",
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

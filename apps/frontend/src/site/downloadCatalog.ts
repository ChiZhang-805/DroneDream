import autonomyMark from "../../../../shared/brand/icons/agent-mark.png";
import fieldMark from "../../../../shared/brand/icons/field-mark.png";
import labMark from "../../../../shared/brand/icons/lab-mark.png";
import simMark from "../../../../shared/brand/icons/sim-mark.png";
import universalMark from "../../../../shared/brand/icons/universal-mark.png";

export type HeaderDownloadId = "universal" | "sim" | "lab" | "field" | "autonomy";

const RELEASE_BASE =
  "https://github.com/ChiZhang-805/DroneDream/releases/download/five-edition-v1.0.0-build-2106";

export const headerDownloadCatalog = [
  {
    id: "universal",
    label: "DroneDream Universal",
    fileName: "DroneDream-Universal_1.0.0_x64-setup.exe",
    sizeBytes: 218_045_843,
    sha256: "90d1f2ceeb8f3016aa4e1178e9d4461fb4e9f5654b14f1e79c03c9399792b3d6",
    mark: universalMark,
  },
  {
    id: "sim",
    label: "DroneDream SIM",
    fileName: "DroneDream-Sim_1.0.0_x64-setup.exe",
    sizeBytes: 216_533_871,
    sha256: "0f6d78d9bdd4f1432cbe17a8911d244290771822d2a10b14bb4df15725de213e",
    mark: simMark,
  },
  {
    id: "lab",
    label: "DroneDream LAB",
    fileName: "DroneDream-Lab_1.0.0_x64-setup.exe",
    sizeBytes: 217_751_153,
    sha256: "50b866c268524c8f5f602b621ce392eaa80fd82bcf38a38c12951daf74901e9a",
    mark: labMark,
  },
  {
    id: "field",
    label: "DroneDream FIELD",
    fileName: "DroneDream-Field_1.0.0_x64-setup.exe",
    sizeBytes: 217_553_447,
    sha256: "8f2f89b8e990ca2c2945698d47646726cb31c3fd008bb174616850673051ac4e",
    mark: fieldMark,
  },
  {
    id: "autonomy",
    label: "DroneDream AGENT",
    fileName: "DroneDream-Agent_1.0.0_x64-setup.exe",
    sizeBytes: 216_890_372,
    sha256: "0296952b54bc50ef58a7589b927c9c433c376fd4f7be144a3b87571db3c9d942",
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

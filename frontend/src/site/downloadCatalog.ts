import autonomyMark from "../../../brand/icons/agent-mark.png";
import fieldMark from "../../../brand/icons/field-mark.png";
import labMark from "../../../brand/icons/lab-mark.png";
import simMark from "../../../brand/icons/sim-mark.png";
import universalMark from "../../../brand/icons/universal-mark.png";

export type HeaderDownloadId = "universal" | "sim" | "lab" | "field" | "autonomy";

const RELEASE_BASE =
  "https://github.com/ChiZhang-805/DroneDream/releases/download/five-edition-v1.0.0-build-1732";
const AGENT_RELEASE_BASE =
  "https://github.com/ChiZhang-805/DroneDream/releases/download/desktop-autonomy-v1.0.0-build-1736";

export const headerDownloadCatalog = [
  {
    id: "universal",
    label: "DroneDream Universal",
    fileName: "DroneDream-Universal_1.0.0_x64-setup.exe",
    sizeBytes: 83_106_080,
    sha256: "725d15c3dfb9a591cf11a759d02319186156f84e203d56d2bb1237b3130f5a7a",
    mark: universalMark,
  },
  {
    id: "sim",
    label: "DroneDream SIM",
    fileName: "DroneDream-Sim_1.0.0_x64-setup.exe",
    sizeBytes: 82_543_483,
    sha256: "a236139b59942558a527bb44f25d111f20f14fdd5d1454f42074abbcb3b29fcd",
    mark: simMark,
  },
  {
    id: "lab",
    label: "DroneDream LAB",
    fileName: "DroneDream-Lab_1.0.0_x64-setup.exe",
    sizeBytes: 83_064_924,
    sha256: "9d5f0d4619756912d1faaeb83e8128925a16dc471d9d683f23fdc7f2dc381854",
    mark: labMark,
  },
  {
    id: "field",
    label: "DroneDream FIELD",
    fileName: "DroneDream-Field_1.0.0_x64-setup.exe",
    sizeBytes: 82_791_388,
    sha256: "891d77fe29f3c1e9a2458ea35f8b848ae356372bbb64f5055040aaf9cf16720d",
    mark: fieldMark,
  },
  {
    id: "autonomy",
    label: "DroneDream AGENT",
    fileName: "DroneDream-Agent_1.0.0_x64-setup.exe",
    sizeBytes: 82_979_305,
    sha256: "16dcfe61ded90b1d54e791f681a2f5d9fe1504b8cdf9cc38e4d1a3616fe53dc6",
    mark: autonomyMark,
  },
].map((download) => ({
  ...download,
  downloadUrl: `${download.id === "autonomy" ? AGENT_RELEASE_BASE : RELEASE_BASE}/${download.fileName}`,
})) as readonly {
  id: HeaderDownloadId;
  label: string;
  fileName: string;
  sizeBytes: number;
  sha256: string;
  mark: string;
  downloadUrl: string;
}[];

import autonomyMark from "../../../brand/icons/agent-mark.png";
import fieldMark from "../../../brand/icons/field-mark.png";
import labMark from "../../../brand/icons/lab-mark.png";
import simMark from "../../../brand/icons/sim-mark.png";
import universalMark from "../../../brand/icons/universal-mark.png";

export type HeaderDownloadId = "universal" | "sim" | "lab" | "field" | "autonomy";

const RELEASE_BASE =
  "https://github.com/ChiZhang-805/DroneDream/releases/download/five-edition-v1.0.0-build-1807";

export const headerDownloadCatalog = [
  {
    id: "universal",
    label: "DroneDream Universal",
    fileName: "DroneDream-Universal_1.0.0_x64-setup.exe",
    sizeBytes: 83_116_515,
    sha256: "c58baf8f7abb35d787dbba3c3d61ffa144fd280e885c8da6091e9e7c799dc1d5",
    mark: universalMark,
  },
  {
    id: "sim",
    label: "DroneDream SIM",
    fileName: "DroneDream-Sim_1.0.0_x64-setup.exe",
    sizeBytes: 82_560_074,
    sha256: "f17b14e6cf56e3a24afbc96b4db2449ff40601837e34d55cb0d0c6461d6c4f86",
    mark: simMark,
  },
  {
    id: "lab",
    label: "DroneDream LAB",
    fileName: "DroneDream-Lab_1.0.0_x64-setup.exe",
    sizeBytes: 83_081_468,
    sha256: "6ff69934e0ab00e61870f3881cfe68c6cb06820a5430090823fa97cb64a99a1f",
    mark: labMark,
  },
  {
    id: "field",
    label: "DroneDream FIELD",
    fileName: "DroneDream-Field_1.0.0_x64-setup.exe",
    sizeBytes: 82_801_834,
    sha256: "417a1752bca42aae46d1e31b8012d243fa95c42478e502d2d4260974ff829242",
    mark: fieldMark,
  },
  {
    id: "autonomy",
    label: "DroneDream AGENT",
    fileName: "DroneDream-Agent_1.0.0_x64-setup.exe",
    sizeBytes: 82_989_307,
    sha256: "43d344216f91affc9c49da2d613fe8e052793d230b1a81a134534c4448934496",
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

import autonomyMark from "../../../brand/icons/agent-mark.png";
import fieldMark from "../../../brand/icons/field-mark.png";
import labMark from "../../../brand/icons/lab-mark.png";
import simMark from "../../../brand/icons/sim-mark.png";
import universalMark from "../../../brand/icons/universal-mark.png";

export type HeaderDownloadId = "universal" | "sim" | "lab" | "field" | "autonomy";

const RELEASE_BASE =
  "https://github.com/ChiZhang-805/DroneDream/releases/download/five-edition-v1.0.0-build-1745";

export const headerDownloadCatalog = [
  {
    id: "universal",
    label: "DroneDream Universal",
    fileName: "DroneDream-Universal_1.0.0_x64-setup.exe",
    sizeBytes: 83_110_929,
    sha256: "d82ea88a255711cfdd81dcdead0bcce948e5f771ce809c3d49289b7a8b98754e",
    mark: universalMark,
  },
  {
    id: "sim",
    label: "DroneDream SIM",
    fileName: "DroneDream-Sim_1.0.0_x64-setup.exe",
    sizeBytes: 82_554_533,
    sha256: "4c229d5efaa1e1c10e59729ba5621f29db6b11c013f4f3f389468909877b9dcd",
    mark: simMark,
  },
  {
    id: "lab",
    label: "DroneDream LAB",
    fileName: "DroneDream-Lab_1.0.0_x64-setup.exe",
    sizeBytes: 83_076_814,
    sha256: "237f531cf052bd3643cfbd81cf5a407bd2b256943f19a97190ee8d4587c110cd",
    mark: labMark,
  },
  {
    id: "field",
    label: "DroneDream FIELD",
    fileName: "DroneDream-Field_1.0.0_x64-setup.exe",
    sizeBytes: 82_806_884,
    sha256: "e23f4a91ff2243c7d7bac66479bff67ce988779d078d3a23e86abb15363968f4",
    mark: fieldMark,
  },
  {
    id: "autonomy",
    label: "DroneDream AGENT",
    fileName: "DroneDream-Agent_1.0.0_x64-setup.exe",
    sizeBytes: 82_993_588,
    sha256: "10e5a5b69191d36f94b78a0ae46c9339b63011858f41cc04ca0619f2969d4c4b",
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

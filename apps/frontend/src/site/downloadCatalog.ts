import autonomyMark from "../../../../shared/brand/icons/agent-mark.png";
import fieldMark from "../../../../shared/brand/icons/field-mark.png";
import labMark from "../../../../shared/brand/icons/lab-mark.png";
import simMark from "../../../../shared/brand/icons/sim-mark.png";
import universalMark from "../../../../shared/brand/icons/universal-mark.png";

export type HeaderDownloadId = "universal" | "sim" | "lab" | "field" | "autonomy";

const RELEASE_BASE =
  "https://github.com/ChiZhang-805/DroneDream/releases/download/five-edition-v1.0.0-build-2128";

export const headerDownloadCatalog = [
  {
    id: "universal",
    label: "DroneDream Universal",
    fileName: "DroneDream-Universal_1.0.0_x64-setup.exe",
    sizeBytes: 217_922_676,
    sha256: "08ae74da7589f6976984fd082c567ec442a4f6ce88c788e04a23009bacad1515",
    mark: universalMark,
  },
  {
    id: "sim",
    label: "DroneDream SIM",
    fileName: "DroneDream-Sim_1.0.0_x64-setup.exe",
    sizeBytes: 217_369_645,
    sha256: "d5e5abc639f15222a3cdc10d8c6bbfcb76189bcf32612750725891db0602bc6d",
    mark: simMark,
  },
  {
    id: "lab",
    label: "DroneDream LAB",
    fileName: "DroneDream-Lab_1.0.0_x64-setup.exe",
    sizeBytes: 217_020_430,
    sha256: "21c4b7eed0829e2776c671555ddbaa8f27642e8503580f1642781befaf5a170c",
    mark: labMark,
  },
  {
    id: "field",
    label: "DroneDream FIELD",
    fileName: "DroneDream-Field_1.0.0_x64-setup.exe",
    sizeBytes: 216_589_442,
    sha256: "5ba1dd090dfca0c3f4ec91f5be8dde8390a9886f61bf49700927048900db6a4d",
    mark: fieldMark,
  },
  {
    id: "autonomy",
    label: "DroneDream AGENT",
    fileName: "DroneDream-Agent_1.0.0_x64-setup.exe",
    sizeBytes: 217_871_085,
    sha256: "cad3c540303a5b30a31915c8f999e06d26dd3cda64f3a625a514b9cd27bc6fce",
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

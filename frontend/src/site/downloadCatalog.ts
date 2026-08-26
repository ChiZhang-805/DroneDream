import autonomyMark from "../../../brand/icons/agent-mark.png";
import fieldMark from "../../../brand/icons/field-mark.png";
import labMark from "../../../brand/icons/lab-mark.png";
import simMark from "../../../brand/icons/sim-mark.png";
import universalMark from "../../../brand/icons/universal-mark.png";

export type HeaderDownloadId = "universal" | "sim" | "lab" | "field" | "autonomy";

const RELEASE_BASE =
  "https://github.com/ChiZhang-805/DroneDream/releases/download/five-edition-v1.0.0-build-1758";

export const headerDownloadCatalog = [
  {
    id: "universal",
    label: "DroneDream Universal",
    fileName: "DroneDream-Universal_1.0.0_x64-setup.exe",
    sizeBytes: 83_118_259,
    sha256: "8f2a120b1cc032f2ab4c81c7361666e8672ca31fa81a8edeb487d3b8ef9f6c9d",
    mark: universalMark,
  },
  {
    id: "sim",
    label: "DroneDream SIM",
    fileName: "DroneDream-Sim_1.0.0_x64-setup.exe",
    sizeBytes: 82_557_004,
    sha256: "1f63402a94b1b2e9bfec2f911b1ed3d43412b4041f8a3aaef62fb965683008af",
    mark: simMark,
  },
  {
    id: "lab",
    label: "DroneDream LAB",
    fileName: "DroneDream-Lab_1.0.0_x64-setup.exe",
    sizeBytes: 83_079_852,
    sha256: "6b9798560028c2bb349d8303b6589f711b6862b8b05474f82d2fb23e885c4508",
    mark: labMark,
  },
  {
    id: "field",
    label: "DroneDream FIELD",
    fileName: "DroneDream-Field_1.0.0_x64-setup.exe",
    sizeBytes: 82_799_229,
    sha256: "1679cab9605eba524ec47e3062f52f3c2829390e084a0f591e06955596a6b096",
    mark: fieldMark,
  },
  {
    id: "autonomy",
    label: "DroneDream AGENT",
    fileName: "DroneDream-Agent_1.0.0_x64-setup.exe",
    sizeBytes: 82_984_272,
    sha256: "a07f1919ec17ec38f2cbe0a377f928dabaf0350cded5b5953ad931a20cc0fc69",
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

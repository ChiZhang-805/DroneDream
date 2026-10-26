import autonomyMark from "../../../../shared/brand/icons/agent-mark.png";
import fieldMark from "../../../../shared/brand/icons/field-mark.png";
import labMark from "../../../../shared/brand/icons/lab-mark.png";
import simMark from "../../../../shared/brand/icons/sim-mark.png";
import universalMark from "../../../../shared/brand/icons/universal-mark.png";

export type HeaderDownloadId = "universal" | "sim" | "lab" | "field" | "autonomy";

const RELEASE_BASE =
  "https://github.com/ChiZhang-805/DroneDream/releases/download/five-edition-v1.0.0-build-2133";

export const headerDownloadCatalog = [
  {
    id: "universal",
    label: "DroneDream Universal",
    fileName: "DroneDream-Universal_1.0.0_x64-setup.exe",
    sizeBytes: 217_915_931,
    sha256: "d3c55125d04e402fa7a0169e1ced52d423af481e170bb6bfd8b91b1606d9fd2f",
    mark: universalMark,
  },
  {
    id: "sim",
    label: "DroneDream SIM",
    fileName: "DroneDream-Sim_1.0.0_x64-setup.exe",
    sizeBytes: 217_375_076,
    sha256: "81e7d8159c579aca6b86f21e1555951f123ec147fe9acda6e5b0d91e722ade6e",
    mark: simMark,
  },
  {
    id: "lab",
    label: "DroneDream LAB",
    fileName: "DroneDream-Lab_1.0.0_x64-setup.exe",
    sizeBytes: 217_885_290,
    sha256: "4637dbd11e7984ee614189c7e2bb91fefcd2f217034ea88deaabe69d0e99dbda",
    mark: labMark,
  },
  {
    id: "field",
    label: "DroneDream FIELD",
    fileName: "DroneDream-Field_1.0.0_x64-setup.exe",
    sizeBytes: 216_577_925,
    sha256: "92aedcfb1869116adf7051e683d8f50528cc419cff0a31e7d98b3f4ed8b17c5f",
    mark: fieldMark,
  },
  {
    id: "autonomy",
    label: "DroneDream AGENT",
    fileName: "DroneDream-Agent_1.0.0_x64-setup.exe",
    sizeBytes: 217_740_904,
    sha256: "5b1cfc3b67668b2b6dfdd2ebe2dbd6b38a836693f6eb23b4a154bdbf8140ed93",
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

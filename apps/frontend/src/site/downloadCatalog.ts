import autonomyMark from "../../../../shared/brand/icons/agent-mark.png";
import fieldMark from "../../../../shared/brand/icons/field-mark.png";
import labMark from "../../../../shared/brand/icons/lab-mark.png";
import simMark from "../../../../shared/brand/icons/sim-mark.png";
import universalMark from "../../../../shared/brand/icons/universal-mark.png";

export type HeaderDownloadId = "universal" | "sim" | "lab" | "field" | "autonomy";

const RELEASE_BASE =
  "https://github.com/ChiZhang-805/DroneDream/releases/download/five-edition-v1.0.0-build-1853";

export const headerDownloadCatalog = [
  {
    id: "universal",
    label: "DroneDream Universal",
    fileName: "DroneDream-Universal_1.0.0_x64-setup.exe",
    sizeBytes: 153_800_039,
    sha256: "c9201779115a2008e2d8882ce621b4e62ec806ff681a59da2131531a5d71c554",
    mark: universalMark,
  },
  {
    id: "sim",
    label: "DroneDream SIM",
    fileName: "DroneDream-Sim_1.0.0_x64-setup.exe",
    sizeBytes: 153_224_009,
    sha256: "9c25f3ea659fec52e77d3cbc60e69fb6bd95c92fe45e6e472ffa3127190526bb",
    mark: simMark,
  },
  {
    id: "lab",
    label: "DroneDream LAB",
    fileName: "DroneDream-Lab_1.0.0_x64-setup.exe",
    sizeBytes: 153_759_871,
    sha256: "be6845231c9fa7172aaeb0228833c3c9328b9fad2d716981cbb7a4c87091dbc7",
    mark: labMark,
  },
  {
    id: "field",
    label: "DroneDream FIELD",
    fileName: "DroneDream-Field_1.0.0_x64-setup.exe",
    sizeBytes: 153_451_720,
    sha256: "e9c5cf47d5b685b1a80be363312e5adffe1ce1f9cedac225439c7d395e0f8e05",
    mark: fieldMark,
  },
  {
    id: "autonomy",
    label: "DroneDream AGENT",
    fileName: "DroneDream-Agent_1.0.0_x64-setup.exe",
    sizeBytes: 153_638_654,
    sha256: "5a57e6bc72a486fa761e7044ef44061ba3c283491c8753d12d8740d38ee75b2c",
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

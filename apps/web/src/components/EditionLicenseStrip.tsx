import agentMark from "../../../../shared/brand/icons/agent-mark.png";
import fieldMark from "../../../../shared/brand/icons/field-mark.png";
import labMark from "../../../../shared/brand/icons/lab-mark.png";
import simMark from "../../../../shared/brand/icons/sim-mark.png";
import universalMark from "../../../../shared/brand/icons/universal-mark.png";
import type { SoftwareEditionId } from "../features/licensing/softwareLicense";
import "./EditionLicenseStrip.css";

const EDITIONS: ReadonlyArray<{ id: SoftwareEditionId; label: string; mark: string }> = [
  { id: "universal", label: "Universal", mark: universalMark },
  { id: "sim", label: "SIM", mark: simMark },
  { id: "lab", label: "LAB", mark: labMark },
  { id: "field", label: "FIELD", mark: fieldMark },
  { id: "autonomy", label: "AGENT", mark: agentMark },
];

export function EditionLicenseStrip({
  licenses,
  locale = "en",
  mode = "licensed",
}: {
  licenses: readonly SoftwareEditionId[];
  locale?: "en" | "zh-CN";
  mode?: "licensed" | "used";
}) {
  const active = new Set(licenses);
  const usedMode = mode === "used";
  return (
    <span className="edition-license-strip" aria-label={
      usedMode
        ? locale === "zh-CN" ? "已使用的软件" : "Used applications"
        : locale === "zh-CN" ? "已授权软件" : "Licensed applications"
    }>
      {EDITIONS.map((edition) => (
        <span
          key={edition.id}
          className={active.has(edition.id) ? "is-active" : "is-inactive"}
          title={`${edition.label}: ${
            active.has(edition.id)
              ? usedMode
                ? locale === "zh-CN" ? "已使用" : "Used"
                : locale === "zh-CN" ? "已授权" : "Licensed"
              : usedMode
                ? locale === "zh-CN" ? "尚未使用" : "Not used"
                : locale === "zh-CN" ? "未授权" : "Not licensed"
          }`}
          aria-label={`${edition.label} ${
            active.has(edition.id)
              ? usedMode
                ? locale === "zh-CN" ? "已使用" : "used"
                : locale === "zh-CN" ? "已授权" : "licensed"
              : usedMode
                ? locale === "zh-CN" ? "尚未使用" : "not used"
                : locale === "zh-CN" ? "未授权" : "not licensed"
          }`}
        >
          <img src={edition.mark} alt="" />
        </span>
      ))}
    </span>
  );
}

import autonomyMark from "../../../brand/commercial/autonomy-mark.png";
import fieldMark from "../../../brand/commercial/field-mark.png";
import labMark from "../../../brand/commercial/lab-mark.png";
import simMark from "../../../brand/commercial/sim-mark.png";
import universalMark from "../../../brand/commercial/universal-mark.png";
import type { SoftwareEditionId } from "../features/licensing/softwareLicense";
import "./EditionLicenseStrip.css";

const EDITIONS: ReadonlyArray<{ id: SoftwareEditionId; label: string; mark: string }> = [
  { id: "universal", label: "Universal", mark: universalMark },
  { id: "sim", label: "SIM", mark: simMark },
  { id: "lab", label: "LAB", mark: labMark },
  { id: "field", label: "FIELD", mark: fieldMark },
  { id: "autonomy", label: "AUTONOMY", mark: autonomyMark },
];

export function EditionLicenseStrip({
  licenses,
  locale = "en",
}: {
  licenses: readonly SoftwareEditionId[];
  locale?: "en" | "zh-CN";
}) {
  const active = new Set(licenses);
  return (
    <span className="edition-license-strip" aria-label={
      locale === "zh-CN" ? "已授权软件" : "Licensed applications"
    }>
      {EDITIONS.map((edition) => (
        <span
          key={edition.id}
          className={active.has(edition.id) ? "is-active" : "is-inactive"}
          title={`${edition.label}: ${
            active.has(edition.id)
              ? locale === "zh-CN" ? "已授权" : "Licensed"
              : locale === "zh-CN" ? "未授权" : "Not licensed"
          }`}
          aria-label={`${edition.label} ${
            active.has(edition.id)
              ? locale === "zh-CN" ? "已授权" : "licensed"
              : locale === "zh-CN" ? "未授权" : "not licensed"
          }`}
        >
          <img src={edition.mark} alt="" />
        </span>
      ))}
    </span>
  );
}

import agentLockup from "../../../brand/icons/agent-lockup.png";
import fieldLockup from "../../../brand/icons/field-lockup.png";
import labLockup from "../../../brand/icons/lab-lockup.png";
import simLockup from "../../../brand/icons/sim-lockup.png";
import universalLockup from "../../../brand/icons/universal-lockup.png";
import type { BrandEditionId } from "../brand/edition-brand.generated";

const LOCKUPS = {
  universal: universalLockup,
  sim: simLockup,
  lab: labLockup,
  field: fieldLockup,
  autonomy: agentLockup,
} as const satisfies Record<BrandEditionId, string>;

type BrandLockupProps = {
  edition?: BrandEditionId;
  className?: string;
};

export function BrandLockup({
  edition = "universal",
  className = "",
}: BrandLockupProps) {
  const classes = [
    "brand-lockup",
    "brand-lockup-primary",
    className,
  ].filter(Boolean).join(" ");

  return (
    <img
      className={classes}
      src={LOCKUPS[edition]}
      alt=""
      aria-hidden="true"
      data-brand-edition={edition}
    />
  );
}

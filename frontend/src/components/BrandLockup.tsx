import fieldLockup from "../../../brand/commercial/field-lockup.png";
import labLockup from "../../../brand/commercial/lab-lockup.png";
import simLockup from "../../../brand/commercial/sim-lockup.png";
import universalLockup from "../../../brand/commercial/universal-lockup.png";
import type { BrandEditionId } from "../brand/edition-brand.generated";

const LOCKUPS = {
  universal: universalLockup,
  sim: simLockup,
  lab: labLockup,
  field: fieldLockup,
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

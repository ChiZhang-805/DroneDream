import fieldCompactLockup from "../assets/brand/field-lockup-compact.png";
import fieldPrimaryLockup from "../assets/brand/field-lockup-primary.png";
import labCompactLockup from "../assets/brand/lab-lockup-compact.png";
import labPrimaryLockup from "../assets/brand/lab-lockup-primary.png";
import simCompactLockup from "../assets/brand/sim-lockup-compact.png";
import simPrimaryLockup from "../assets/brand/sim-lockup-primary.png";
import universalCompactLockup from "../assets/brand/universal-lockup-compact.png";
import universalPrimaryLockup from "../assets/brand/universal-lockup-primary.png";
import type { BrandEditionId } from "../brand/edition-brand.generated";

const LOCKUPS = {
  universal: {
    primary: universalPrimaryLockup,
    compact: universalCompactLockup,
  },
  sim: {
    primary: simPrimaryLockup,
    compact: simCompactLockup,
  },
  lab: {
    primary: labPrimaryLockup,
    compact: labCompactLockup,
  },
  field: {
    primary: fieldPrimaryLockup,
    compact: fieldCompactLockup,
  },
} as const satisfies Record<BrandEditionId, Record<"primary" | "compact", string>>;

type BrandLockupProps = {
  variant?: "primary" | "compact";
  edition?: BrandEditionId;
  className?: string;
};

export function BrandLockup({
  variant = "primary",
  edition = "universal",
  className = "",
}: BrandLockupProps) {
  const classes = [
    "brand-lockup",
    `brand-lockup-${variant}`,
    className,
  ].filter(Boolean).join(" ");

  return (
    <img
      className={classes}
      src={LOCKUPS[edition][variant]}
      alt=""
      aria-hidden="true"
      data-brand-edition={edition}
    />
  );
}

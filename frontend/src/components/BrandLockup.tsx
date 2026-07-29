import compactLockup from "../assets/drone-dream-lockup-compact.png";
import primaryLockup from "../assets/drone-dream-lockup-primary.png";

type BrandLockupProps = {
  variant?: "primary" | "compact";
  className?: string;
};

export function BrandLockup({
  variant = "primary",
  className = "",
}: BrandLockupProps) {
  const classes = [
    "brand-lockup",
    `brand-lockup-${variant}`,
    className,
  ].filter(Boolean).join(" ");

  const source = variant === "primary" ? primaryLockup : compactLockup;
  return <img className={classes} src={source} alt="" aria-hidden="true" />;
}

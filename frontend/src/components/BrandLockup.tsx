import primaryLockup from "../assets/drone-dream-lockup-primary.png";
import compactLockup from "../assets/drone-dream-lockup-compact.png";

type BrandLockupProps = {
  variant?: "primary" | "compact";
  className?: string;
};

export function BrandLockup({
  variant = "primary",
  className = "",
}: BrandLockupProps) {
  const source = variant === "compact" ? compactLockup : primaryLockup;
  const classes = [
    "brand-lockup",
    `brand-lockup-${variant}`,
    className,
  ].filter(Boolean).join(" ");

  return <img className={classes} src={source} alt="" aria-hidden="true" />;
}

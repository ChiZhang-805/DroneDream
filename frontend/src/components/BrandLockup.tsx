import compactLockup from "../assets/drone-dream-lockup-compact.png";
import brandMark from "../assets/drone-dream-mark.png";
import primaryWordmark from "../../../docs/assets/brand/drone-dream-wordmark-primary.png";

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

  if (variant === "primary") {
    return (
      <span className={classes} aria-hidden="true">
        <img className="brand-lockup-mark" src={brandMark} alt="" />
        <img className="brand-lockup-wordmark" src={primaryWordmark} alt="" />
      </span>
    );
  }

  return <img className={classes} src={compactLockup} alt="" aria-hidden="true" />;
}

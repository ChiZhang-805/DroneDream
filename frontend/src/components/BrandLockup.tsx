import { appEdition } from "../edition";
import { resolveBrandLockupSource } from "./brandAssets";

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

  const source = resolveBrandLockupSource(appEdition, variant);
  return <img className={classes} src={source} alt="" aria-hidden="true" />;
}

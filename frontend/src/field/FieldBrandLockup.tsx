import fieldCompactLockup from "../assets/brand/field-lockup-compact.png";
import fieldPrimaryLockup from "../assets/brand/field-lockup-primary.png";

type FieldBrandLockupProps = {
  variant?: "primary" | "compact";
  className?: string;
};

export function FieldBrandLockup({
  variant = "primary",
  className = "",
}: FieldBrandLockupProps) {
  const classes = [
    "brand-lockup",
    `brand-lockup-${variant}`,
    className,
  ].filter(Boolean).join(" ");

  return (
    <img
      className={classes}
      src={variant === "compact" ? fieldCompactLockup : fieldPrimaryLockup}
      alt=""
      aria-hidden="true"
      data-brand-edition="field"
    />
  );
}

// The Field Vite profile aliases shared BrandLockup imports to this exact
// edition-owned implementation so shared surfaces cannot pull other assets in.
export { FieldBrandLockup as BrandLockup };

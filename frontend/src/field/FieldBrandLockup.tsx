import fieldLockup from "../../../brand/icons/field-lockup.png";

type FieldBrandLockupProps = {
  className?: string;
};

export function FieldBrandLockup({
  className = "",
}: FieldBrandLockupProps) {
  const classes = [
    "brand-lockup",
    "brand-lockup-primary",
    className,
  ].filter(Boolean).join(" ");

  return (
    <img
      className={classes}
      src={fieldLockup}
      alt=""
      aria-hidden="true"
      data-brand-edition="field"
    />
  );
}

// The Field Vite profile aliases shared BrandLockup imports to this exact
// edition-owned implementation so shared surfaces cannot pull other assets in.
export { FieldBrandLockup as BrandLockup };

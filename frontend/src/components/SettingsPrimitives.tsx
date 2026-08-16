import type { ReactNode } from "react";

export const SETTINGS_LOCALES = [
  { id: "en", label: "English", region: "west" },
  { id: "zh-CN", label: "简体中文", region: "east" },
  { id: "zh-TW", label: "繁體中文", region: "east" },
  { id: "es", label: "Español", region: "west" },
  { id: "ja", label: "日本語", region: "east" },
  { id: "ko", label: "한국어", region: "east" },
] as const;

export function SettingsLanguageRegionIcon({
  region,
}: {
  region: "west" | "east";
}) {
  return (
    <span
      className={`launcher-language-icon launcher-language-icon-${region}`}
      aria-hidden="true"
    >
      <svg viewBox="0 0 24 24">
        <circle cx="12" cy="12" r="8.25" />
        <path d="M3.9 12h16.2M12 3.75c2.1 2.25 3.2 5 3.2 8.25S14.1 18 12 20.25C9.9 18 8.8 15.25 8.8 12S9.9 6 12 3.75Z" />
        <circle
          className="launcher-language-region"
          cx={region === "west" ? "8" : "16"}
          cy="10"
          r="1.65"
        />
      </svg>
    </span>
  );
}

export function SettingsToggle({
  checked,
  className,
  disabled = false,
  label,
  onChange,
}: {
  checked: boolean;
  className?: string;
  disabled?: boolean;
  label: ReactNode;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className={`settings-toggle-row${className ? ` ${className}` : ""}`}>
      <span>{label}</span>
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
      />
      <i aria-hidden="true" />
    </label>
  );
}

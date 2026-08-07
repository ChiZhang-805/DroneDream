import { Layers3 } from "lucide-react";

import { BrandLockup } from "./BrandLockup";
import {
  EDITION_BRAND_TOKENS,
} from "../brand/edition-brand.generated";
import {
  UNIVERSAL_WORKSPACE_IDS,
  type UniversalWorkspaceId,
} from "../features/distribution/universalMode";

const COPY = {
  en: {
    label: "Workspace mode",
    note: "Switches the workspace only. It does not start Model + Harness, an experiment, or hardware access.",
  },
  "zh-CN": {
    label: "工作区",
    note: "这里只切换工作区，不会启动 Model + Harness、实验或真机权限。",
  },
} as const;

export function UniversalModeSwitch({
  mode,
  locale,
  onChange,
}: {
  mode: UniversalWorkspaceId;
  locale: keyof typeof COPY;
  onChange: (mode: UniversalWorkspaceId) => void;
}) {
  const copy = COPY[locale];
  return (
    <section
      className="universal-mode-switch"
      aria-label={copy.label}
      data-presentation-only="true"
      data-grants-hardware-authority="false"
    >
      <div className="universal-mode-switch-current" data-brand-edition={mode}>
        <Layers3 aria-hidden="true" strokeWidth={1.8} />
        <BrandLockup edition={mode} variant="compact" />
      </div>
      <label>
        <span className="sr-only">{copy.label}</span>
        <select
          aria-label={copy.label}
          value={mode}
          onChange={(event) => onChange(event.target.value as UniversalWorkspaceId)}
        >
          {UNIVERSAL_WORKSPACE_IDS.map((edition) => (
            <option key={edition} value={edition}>
              {EDITION_BRAND_TOKENS[edition].productName}
            </option>
          ))}
        </select>
      </label>
      <p>{copy.note}</p>
    </section>
  );
}

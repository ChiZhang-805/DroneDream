import { Layers3 } from "lucide-react";

import { BrandLockup } from "./BrandLockup";
import {
  type BrandEditionId,
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

const SELECTABLE_SURFACES: BrandEditionId[] = ["universal", ...UNIVERSAL_WORKSPACE_IDS];

export function UniversalModeSwitch({
  mode,
  activeEdition = mode,
  locale,
  onChange,
  onOpenUniversal,
}: {
  mode: UniversalWorkspaceId;
  activeEdition?: BrandEditionId;
  locale: keyof typeof COPY;
  onChange: (mode: UniversalWorkspaceId) => void;
  onOpenUniversal?: () => void;
}) {
  const copy = COPY[locale];
  return (
    <section
      className="universal-mode-switch"
      aria-label={copy.label}
      data-presentation-only="true"
      data-grants-hardware-authority="false"
    >
      <div className="universal-mode-switch-current" data-brand-edition={activeEdition}>
        <Layers3 aria-hidden="true" strokeWidth={1.8} />
        <BrandLockup edition={activeEdition} variant="compact" />
      </div>
      <label>
        <span className="sr-only">{copy.label}</span>
        <select
          aria-label={copy.label}
          value={activeEdition}
          onChange={(event) => {
            if (event.target.value === "universal") {
              onOpenUniversal?.();
              return;
            }
            onChange(event.target.value as UniversalWorkspaceId);
          }}
        >
          {SELECTABLE_SURFACES.map((edition) => (
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

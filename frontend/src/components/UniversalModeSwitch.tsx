import { Layers3 } from "lucide-react";

import { BrandLockup } from "./BrandLockup";
import {
  BRAND_EDITION_IDS,
  EDITION_BRAND_TOKENS,
  type BrandEditionId,
} from "../brand/edition-brand.generated";

const COPY = {
  en: {
    label: "Workspace mode",
    note: "Changes the interface and workflow only. Hardware authority still requires installed modules, a validated Vehicle Pack, and native/backend/runtime approval.",
  },
  "zh-CN": {
    label: "工作模式",
    note: "这里只切换界面和工作流程。真机权限仍必须通过已安装模块、已验证机型包，以及 native、后端和 Runtime 三层审批。",
  },
} as const;

export function UniversalModeSwitch({
  mode,
  locale,
  onChange,
}: {
  mode: BrandEditionId;
  locale: keyof typeof COPY;
  onChange: (mode: BrandEditionId) => void;
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
          onChange={(event) => onChange(event.target.value as BrandEditionId)}
        >
          {BRAND_EDITION_IDS.map((edition) => (
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

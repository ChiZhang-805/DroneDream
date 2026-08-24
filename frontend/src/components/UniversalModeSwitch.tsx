import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown } from "lucide-react";

import agentLockup from "../../../brand/icons/agent-lockup.png";
import fieldLockup from "../../../brand/icons/field-lockup.png";
import labLockup from "../../../brand/icons/lab-lockup.png";
import simLockup from "../../../brand/icons/sim-lockup.png";
import universalLockup from "../../../brand/icons/universal-lockup.png";
import type { BrandEditionId } from "../brand/edition-brand.generated";
import {
  UNIVERSAL_WORKSPACE_IDS,
  type UniversalWorkspaceId,
} from "../features/distribution/universalMode";

const COPY = {
  en: { label: "Switch DroneDream edition", menuLabel: "DroneDream editions" },
  "zh-CN": { label: "切换 DroneDream 版本", menuLabel: "DroneDream 版本" },
} as const;

const SELECTABLE_SURFACES: BrandEditionId[] = [...UNIVERSAL_WORKSPACE_IDS];
const EDITION_LABELS: Record<BrandEditionId, string> = {
  universal: "DroneDream",
  sim: "DroneDream · SIM",
  lab: "DroneDream · LAB",
  field: "DroneDream · FIELD",
  autonomy: "DroneDream · AGENT",
};
const EDITION_LOCKUPS: Record<BrandEditionId, string> = {
  universal: universalLockup,
  sim: simLockup,
  lab: labLockup,
  field: fieldLockup,
  autonomy: agentLockup,
};

function EditionBrand({ edition }: { edition: BrandEditionId }) {
  return (
    <span className="workspace-switch-brand" data-brand-edition={edition}>
      <img src={EDITION_LOCKUPS[edition]} alt="" aria-hidden="true" />
      <span className="sr-only">{EDITION_LABELS[edition]}</span>
    </span>
  );
}

export function UniversalModeSwitch({
  mode,
  activeEdition = mode,
  locale,
  onChange,
}: {
  mode: UniversalWorkspaceId;
  activeEdition?: BrandEditionId;
  locale: keyof typeof COPY;
  onChange: (mode: UniversalWorkspaceId) => void;
}) {
  const copy = COPY[locale];
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return undefined;
    const closeOnOutsidePointer = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setOpen(false);
      triggerRef.current?.focus();
    };
    document.addEventListener("pointerdown", closeOnOutsidePointer);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsidePointer);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  const selectEdition = (edition: BrandEditionId) => {
    setOpen(false);
    if (edition === activeEdition) return;
    onChange(edition as UniversalWorkspaceId);
  };

  return (
    <section
      ref={rootRef}
      className="universal-mode-switch"
      aria-label={copy.label}
      data-presentation-only="true"
      data-grants-hardware-authority="false"
    >
      <button
        ref={triggerRef}
        type="button"
        className="universal-mode-switch-trigger"
        aria-label={copy.label}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
      >
        <EditionBrand edition={activeEdition} />
        <ChevronDown className="universal-mode-switch-chevron" aria-hidden="true" strokeWidth={2} />
      </button>
      {open ? (
        <div className="universal-mode-switch-menu" role="menu" aria-label={copy.menuLabel}>
          {SELECTABLE_SURFACES.map((edition) => {
            const current = edition === activeEdition;
            return (
              <button
                key={edition}
                type="button"
                role="menuitemradio"
                aria-label={EDITION_LABELS[edition]}
                aria-checked={current}
                onClick={() => selectEdition(edition)}
              >
                <EditionBrand edition={edition} />
                {current ? <Check aria-hidden="true" strokeWidth={2.2} /> : null}
              </button>
            );
          })}
        </div>
      ) : null}
    </section>
  );
}

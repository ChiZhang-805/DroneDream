import {
  Activity,
  Bot,
  Database,
  SlidersHorizontal,
  X,
  type LucideIcon,
} from "lucide-react";
import {
  useRef,
  type KeyboardEvent,
  type ReactNode,
  type RefObject,
} from "react";

import type { BrandEditionId } from "../brand/edition-brand.generated";
import { BrandLockup } from "./BrandLockup";

export type SettingsSurfaceTabId = "general" | "memory" | "model" | "runtime";

export type SettingsSurfaceTab = Readonly<{
  id: SettingsSurfaceTabId;
  label: string;
}>;

const TAB_ICONS: Readonly<Record<SettingsSurfaceTabId, LucideIcon>> = {
  general: SlidersHorizontal,
  memory: Database,
  model: Bot,
  runtime: Activity,
};

export function EditionSettingsSurface({
  activeTab,
  closeLabel,
  closeRef,
  edition,
  onClose,
  onTabChange,
  tabs,
  title,
  children,
  consumerProfile = "shared",
}: {
  activeTab: SettingsSurfaceTabId;
  closeLabel: string;
  closeRef?: RefObject<HTMLButtonElement>;
  edition: BrandEditionId;
  onClose: () => void;
  onTabChange: (tab: SettingsSurfaceTabId) => void;
  tabs: readonly SettingsSurfaceTab[];
  title: string;
  children: ReactNode;
  consumerProfile?: "shared" | "universal" | "sim" | "lab" | "field-lightweight" | "autonomy";
}) {
  const tabRefs = useRef(new Map<SettingsSurfaceTabId, HTMLButtonElement>());
  const moveFocus = (event: KeyboardEvent<HTMLButtonElement>, currentIndex: number) => {
    let nextIndex: number;
    if (event.key === "ArrowRight" || event.key === "ArrowDown") {
      nextIndex = (currentIndex + 1) % tabs.length;
    } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
      nextIndex = (currentIndex - 1 + tabs.length) % tabs.length;
    } else if (event.key === "Home") {
      nextIndex = 0;
    } else if (event.key === "End") {
      nextIndex = tabs.length - 1;
    } else {
      return;
    }
    event.preventDefault();
    const next = tabs[nextIndex];
    if (!next) return;
    onTabChange(next.id);
    tabRefs.current.get(next.id)?.focus();
  };

  return (
    <section
      className="launcher-settings-dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby="launcher-settings-title"
      data-brand-edition={edition}
      data-settings-consumer={consumerProfile}
      data-presentation-only="true"
      data-grants-hardware-authority="false"
    >
      <div className="launcher-settings-heading">
        <div className="launcher-settings-title-lockup">
          <BrandLockup edition={edition} variant="compact" />
          <h2 id="launcher-settings-title">{title}</h2>
        </div>
        <button
          ref={closeRef}
          type="button"
          className="launcher-settings-close"
          aria-label={closeLabel}
          title={closeLabel}
          onClick={onClose}
        >
          <X aria-hidden="true" />
        </button>
      </div>
      <div className="launcher-settings-tabs" role="tablist" aria-label={title}>
        {tabs.map((tab, index) => {
          const Icon = TAB_ICONS[tab.id];
          const selected = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              ref={(element) => {
                if (element) tabRefs.current.set(tab.id, element);
                else tabRefs.current.delete(tab.id);
              }}
              type="button"
              role="tab"
              id={`settings-tab-${tab.id}`}
              aria-controls={`settings-panel-${tab.id}`}
              aria-selected={selected}
              tabIndex={selected ? 0 : -1}
              title={tab.label}
              onClick={() => onTabChange(tab.id)}
              onKeyDown={(event) => moveFocus(event, index)}
            >
              <Icon aria-hidden="true" />
              <span>{tab.label}</span>
            </button>
          );
        })}
      </div>
      <div className="launcher-settings-panels">{children}</div>
    </section>
  );
}

export function EditionSettingsPanel({
  active,
  id,
  children,
}: {
  active: boolean;
  id: SettingsSurfaceTabId;
  children: ReactNode;
}) {
  return (
    <div
      id={`settings-panel-${id}`}
      className="launcher-settings-panel"
      role="tabpanel"
      aria-labelledby={`settings-tab-${id}`}
      data-settings-panel={id}
      hidden={!active}
      tabIndex={0}
    >
      {children}
    </div>
  );
}

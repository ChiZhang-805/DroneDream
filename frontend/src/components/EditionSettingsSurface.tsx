import {
  Activity,
  ArrowLeft,
  Bot,
  Database,
  GraduationCap,
  SlidersHorizontal,
  X,
  type LucideIcon,
} from "lucide-react";
import {
  useEffect,
  useRef,
  type KeyboardEvent,
  type ReactNode,
  type RefObject,
} from "react";

import type { BrandEditionId } from "../brand/edition-brand.generated";

export type SettingsSurfaceTabId = "general" | "memory" | "model" | "course" | "runtime";

export type SettingsSurfaceTab = Readonly<{
  id: SettingsSurfaceTabId;
  label: string;
  disabled?: boolean;
}>;

const TAB_ICONS: Readonly<Record<SettingsSurfaceTabId, LucideIcon>> = {
  general: SlidersHorizontal,
  memory: Database,
  model: Bot,
  course: GraduationCap,
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
  presentation = "dialog",
  backLabel,
  headerAction,
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
  consumerProfile?: "shared" | BrandEditionId;
  presentation?: "dialog" | "workspace";
  backLabel?: string;
  headerAction?: ReactNode;
}) {
  const tabRefs = useRef(new Map<SettingsSurfaceTabId, HTMLButtonElement>());
  useEffect(() => {
    if (presentation !== "workspace") return undefined;
    const frame = window.requestAnimationFrame(() => {
      tabRefs.current.get(activeTab)?.focus();
    });
    return () => window.cancelAnimationFrame(frame);
  }, [activeTab, presentation]);
  useEffect(() => {
    if (presentation !== "workspace") return undefined;
    const returnToApplication = (event: globalThis.KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      const nestedModal = document.querySelector<HTMLElement>(
        '[role="dialog"][aria-modal="true"]',
      );
      if (nestedModal) return;
      event.preventDefault();
      onClose();
    };
    document.addEventListener("keydown", returnToApplication);
    return () => document.removeEventListener("keydown", returnToApplication);
  }, [onClose, presentation]);
  const moveFocus = (event: KeyboardEvent<HTMLButtonElement>, currentIndex: number) => {
    let direction = 0;
    let nextIndex: number;
    if (event.key === "ArrowRight" || event.key === "ArrowDown") {
      direction = 1;
      nextIndex = currentIndex;
    } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
      direction = -1;
      nextIndex = currentIndex;
    } else if (event.key === "Home") {
      nextIndex = tabs.findIndex((tab) => !tab.disabled);
    } else if (event.key === "End") {
      nextIndex = tabs.length - 1;
      while (nextIndex >= 0 && tabs[nextIndex]?.disabled) nextIndex -= 1;
    } else {
      return;
    }
    event.preventDefault();
    if (direction !== 0) {
      for (let attempts = 0; attempts < tabs.length; attempts += 1) {
        nextIndex = (nextIndex + direction + tabs.length) % tabs.length;
        if (!tabs[nextIndex]?.disabled) break;
      }
    }
    const next = tabs[nextIndex];
    if (!next || next.disabled) return;
    onTabChange(next.id);
    tabRefs.current.get(next.id)?.focus();
  };

  const navigation = (
    <div
      className="launcher-settings-tabs"
      role="tablist"
      aria-label={title}
      aria-orientation={presentation === "workspace" ? "vertical" : "horizontal"}
    >
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
            aria-disabled={tab.disabled || undefined}
            disabled={tab.disabled}
            tabIndex={!tab.disabled && selected ? 0 : -1}
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
  );

  return (
    <section
      className={`launcher-settings-dialog${presentation === "workspace" ? " settings-workspace-surface" : ""}`}
      role={presentation === "workspace" ? "region" : "dialog"}
      aria-modal={presentation === "dialog" ? "true" : undefined}
      aria-labelledby="launcher-settings-title"
      data-brand-edition={edition}
      data-settings-consumer={consumerProfile}
      data-presentation-only="true"
      data-grants-hardware-authority="false"
    >
      {presentation === "workspace" ? (
        <aside className="settings-workspace-sidebar">
          <h2 id="launcher-settings-title">{title}</h2>
          {navigation}
          <button
            type="button"
            className="settings-workspace-back"
            onClick={onClose}
          >
            <ArrowLeft aria-hidden="true" />
            <span>{backLabel ?? closeLabel}</span>
          </button>
        </aside>
      ) : null}
      <div className={presentation === "workspace" ? "settings-workspace-content" : undefined}>
        <div className="launcher-settings-heading">
          <div className="launcher-settings-title-lockup">
            <h2 id={presentation === "workspace" ? "settings-workspace-active-title" : "launcher-settings-title"}>
              {presentation === "workspace"
                ? tabs.find((tab) => tab.id === activeTab)?.label ?? title
                : title}
            </h2>
          </div>
          {presentation === "workspace" ? headerAction ?? null : (
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
          )}
        </div>
        {presentation === "workspace" ? null : navigation}
        <div className="launcher-settings-panels">{children}</div>
      </div>
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

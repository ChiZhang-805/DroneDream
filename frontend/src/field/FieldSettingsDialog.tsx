import { Check, Languages, ShieldCheck } from "lucide-react";
import { useState, type RefObject } from "react";

import {
  EditionSettingsPanel,
  EditionSettingsSurface,
  type SettingsSurfaceTab,
  type SettingsSurfaceTabId,
} from "../components/EditionSettingsSurface";
import type { FieldLocale } from "./catalog";

const COPY = {
  en: {
    title: "Field settings",
    close: "Close settings",
    general: "General",
    safety: "Safety",
    language: "Interface language",
    english: "English",
    chinese: "Simplified Chinese",
    profile: "Execution profile",
    profileValue: "field-lightweight",
    packs: "Validated Vehicle Packs",
    quorum: "Three-layer quorum",
    authority: "Hardware authority",
    missing: "Missing",
    denied: "Denied",
  },
  "zh-CN": {
    title: "Field 设置",
    close: "关闭设置",
    general: "常规",
    safety: "安全",
    language: "界面语言",
    english: "English",
    chinese: "简体中文",
    profile: "执行配置",
    profileValue: "field-lightweight",
    packs: "已验证机型包",
    quorum: "三层仲裁",
    authority: "硬件权限",
    missing: "缺失",
    denied: "拒绝",
  },
} as const;

export function FieldSettingsDialog({
  closeRef,
  locale,
  onClose,
  onLocaleChange,
}: {
  closeRef: RefObject<HTMLButtonElement>;
  locale: FieldLocale;
  onClose: () => void;
  onLocaleChange: (locale: FieldLocale) => void;
}) {
  const [activeTab, setActiveTab] = useState<SettingsSurfaceTabId>("general");
  const copy = COPY[locale];
  const tabs: readonly SettingsSurfaceTab[] = [
    { id: "general", label: copy.general },
    { id: "runtime", label: copy.safety },
  ];

  return (
    <EditionSettingsSurface
      activeTab={activeTab}
      closeLabel={copy.close}
      closeRef={closeRef}
      edition="field"
      onClose={onClose}
      onTabChange={setActiveTab}
      tabs={tabs}
      title={copy.title}
      consumerProfile="field-lightweight"
    >
      <EditionSettingsPanel active={activeTab === "general"} id="general">
        <fieldset className="field-settings-languages" aria-label={copy.language}>
          {([
            ["en", copy.english],
            ["zh-CN", copy.chinese],
          ] as const).map(([id, label]) => (
            <button
              key={id}
              type="button"
              className={locale === id ? "selected" : undefined}
              aria-pressed={locale === id}
              onClick={() => onLocaleChange(id)}
            >
              <Languages aria-hidden="true" />
              <span>{label}</span>
              {locale === id ? <Check aria-hidden="true" /> : null}
            </button>
          ))}
        </fieldset>
      </EditionSettingsPanel>
      <EditionSettingsPanel active={activeTab === "runtime"} id="runtime">
        <dl className="field-settings-safety" data-authority="false">
          <div><dt>{copy.profile}</dt><dd>{copy.profileValue}</dd></div>
          <div><dt>{copy.packs}</dt><dd>0</dd></div>
          <div><dt>{copy.quorum}</dt><dd>{copy.missing}</dd></div>
          <div><dt>{copy.authority}</dt><dd><ShieldCheck aria-hidden="true" />{copy.denied}</dd></div>
        </dl>
      </EditionSettingsPanel>
    </EditionSettingsSurface>
  );
}

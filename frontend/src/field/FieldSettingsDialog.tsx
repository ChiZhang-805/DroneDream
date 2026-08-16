import { Check, ExternalLink, Languages, ShieldCheck } from "lucide-react";
import { useState, type RefObject } from "react";

import {
  EditionSettingsPanel,
  EditionSettingsSurface,
  type SettingsSurfaceTab,
  type SettingsSurfaceTabId,
} from "../components/EditionSettingsSurface";
import { useAuthOrLocal } from "../features/auth/AuthContext";
import type { FieldLocale } from "./catalog";

const ECE498BH_COURSE_URL =
  "https://binhu7.github.io/courses/ECE498/Spring2025/ECE498home.html";

const COPY = {
  en: {
    title: "Field settings",
    close: "Close settings",
    general: "General",
    memory: "Memory",
    model: "Models",
    safety: "Safety",
    course: "ECE498BH",
    openCourse: "Open course",
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
    missionMemory: "Mission memory",
    modelAccount: "Model account",
  },
  "zh-CN": {
    title: "Field 设置",
    close: "关闭设置",
    general: "常规",
    memory: "记忆",
    model: "模型",
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
    missionMemory: "任务记忆",
    modelAccount: "模型账户",
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
  const { account } = useAuthOrLocal();
  const [memoryEnabled, setMemoryEnabled] = useState(() => {
    try {
      return window.localStorage.getItem("dd.field.memory.enabled") !== "false";
    } catch {
      return true;
    }
  });
  const copy = COPY[locale];
  const courseLabel = locale === "zh-CN" ? "\u6253\u5f00\u8bfe\u7a0b" : "Open course";
  const courseBody = locale === "zh-CN" ? "\u5de5\u7a0b\u63a8\u7406\u8bfe\u7a0b\u8d44\u6e90" : "Engineering reasoning course resources";
  const tabs: readonly SettingsSurfaceTab[] = [
    { id: "general", label: copy.general },
    { id: "memory", label: copy.memory },
    { id: "model", label: copy.model, disabled: !account },
    { id: "course", label: "ECE498BH" },
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
      <EditionSettingsPanel active={activeTab === "memory"} id="memory">
        <div className="field-settings-memory">
          <label>
            <span>{copy.missionMemory}</span>
            <input
              type="checkbox"
              checked={memoryEnabled}
              onChange={(event) => {
                const enabled = event.target.checked;
                setMemoryEnabled(enabled);
                try {
                  window.localStorage.setItem("dd.field.memory.enabled", String(enabled));
                } catch {
                  // Storage is optional; the setting remains valid for this session.
                }
              }}
            />
          </label>
        </div>
      </EditionSettingsPanel>
      <EditionSettingsPanel active={activeTab === "model"} id="model">
        {account ? (
          <dl className="field-settings-safety">
            <div><dt>{copy.modelAccount}</dt><dd>{account.displayName}</dd></div>
          </dl>
        ) : null}
      </EditionSettingsPanel>
      <EditionSettingsPanel active={activeTab === "runtime"} id="runtime">
        <dl className="field-settings-safety" data-authority="false">
          <div><dt>{copy.profile}</dt><dd>{copy.profileValue}</dd></div>
          <div><dt>{copy.packs}</dt><dd>0</dd></div>
          <div><dt>{copy.quorum}</dt><dd>{copy.missing}</dd></div>
          <div><dt>{copy.authority}</dt><dd><ShieldCheck aria-hidden="true" />{copy.denied}</dd></div>
        </dl>
      </EditionSettingsPanel>
      <EditionSettingsPanel active={activeTab === "course"} id="course">
        <div className="field-settings-course">
          <div><strong>ECE498BH</strong><span>{courseBody}</span></div>
          <a href={ECE498BH_COURSE_URL} target="_blank" rel="noreferrer">
            {courseLabel}<ExternalLink aria-hidden="true" />
          </a>
        </div>
      </EditionSettingsPanel>
    </EditionSettingsSurface>
  );
}

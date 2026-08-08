import { LockKeyhole, RadioTower, ShieldCheck } from "lucide-react";

import { FieldApp } from "../field/FieldApp";
import { useI18n } from "../i18n/I18nProvider";
import "../field/field.css";
import "./lab-hardware.css";

const COPY = {
  en: {
    eyebrow: "LAB HARDWARE DOMAIN",
    title: "Hardware laboratory",
    body: "FIELD-grade discovery, protocol inspection, parameter snapshots, rollback planning, preflight review, and recorded-evidence Harness tuning are integrated here for Sim-to-Real and Real-to-Sim work.",
    safety: "Zero Vehicle Packs are validated. Discovery and bounded read-only evidence tools do not grant parameter write, arm, flight, or HITL authority.",
  },
  "zh-CN": {
    eyebrow: "LAB 真机实验域",
    title: "真机实验室",
    body: "这里集成 FIELD 级设备发现、协议检查、参数快照、回滚计划、飞前复核和记录证据 Harness 调优，用于 Sim-to-Real 与 Real-to-Sim 闭环。",
    safety: "当前已验证 Vehicle Pack 数量为零；发现和受限只读证据工具不会授予写参数、解锁、飞行或 HITL 权限。",
  },
} as const;

export function LabHardwareWorkspace() {
  const { locale } = useI18n();
  const copy = COPY[locale];
  return (
    <section
      className="lab-hardware-workspace"
      data-brand-edition="lab"
      data-presentation-only="true"
      data-grants-hardware-authority="false"
    >
      <header className="lab-hardware-heading">
        <div>
          <span><RadioTower aria-hidden="true" />{copy.eyebrow}</span>
          <h1>{copy.title}</h1>
          <p>{copy.body}</p>
        </div>
        <div className="lab-hardware-deny" role="status">
          <LockKeyhole aria-hidden="true" />
          <strong>DENY</strong>
          <small>0 validated packs</small>
        </div>
      </header>
      <div className="lab-hardware-safety">
        <ShieldCheck aria-hidden="true" />
        <p>{copy.safety}</p>
      </div>
      <FieldApp initialLocale={locale} embeddedInLab />
    </section>
  );
}

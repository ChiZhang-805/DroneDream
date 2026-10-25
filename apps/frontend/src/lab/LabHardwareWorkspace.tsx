import { RadioTower } from "lucide-react";

import { FieldApp } from "../field/FieldApp";
import { useI18n } from "../i18n/I18nProvider";
import "./lab-hardware.css";

const COPY = {
  en: {
    title: "Hardware laboratory",
  },
  "zh-CN": {
    title: "真机实验室",
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
          <h1><RadioTower aria-hidden="true" />{copy.title}</h1>
        </div>
      </header>
      <FieldApp initialLocale={locale} embeddedInLab />
    </section>
  );
}

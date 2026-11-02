import { useParams } from "react-router-dom";

import { useI18n } from "../i18n/I18nProvider";
import { FieldApp, type FieldPageId } from "./FieldApp";

/**
 * Router ownership stays outside the reusable hardware-domain workspace. This
 * adapter maps the primary product sidebar onto Field's bounded presentation
 * pages without introducing a second navigation surface inside the console.
 */
export function UniversalFieldApp() {
  const { locale } = useI18n();
  const { fieldPage } = useParams();
  const activePageOverride: FieldPageId = fieldPage === "tuning"
    ? "tuning"
    : fieldPage === "operations"
      ? "operations"
      : "device";

  return (
    <FieldApp
      initialLocale={locale}
      embeddedInConsole
      activePageOverride={activePageOverride}
    />
  );
}

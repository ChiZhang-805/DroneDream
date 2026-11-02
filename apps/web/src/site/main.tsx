import React from "react";
import ReactDOM from "react-dom/client";
import "@fontsource-variable/space-grotesk/wght.css";

import { AuthProvider } from "../features/auth/AuthContext";
import { hostedConsoleRecoveryHref } from "../hostedConsoleRouting";
import { I18nProvider } from "../i18n/I18nProvider";
import "../styles.css";
import { SiteApp } from "./SiteApp";
import "./site.css";
import "./aliyun-manual-community.css";

const consoleRecoveryHref = hostedConsoleRecoveryHref(
  window.location.pathname,
  window.location.search,
  window.location.hash,
);

if (consoleRecoveryHref) {
  window.location.replace(consoleRecoveryHref);
} else {
  ReactDOM.createRoot(document.getElementById("site-root")!).render(
    <React.StrictMode>
      <I18nProvider>
        <AuthProvider>
          <SiteApp />
        </AuthProvider>
      </I18nProvider>
    </React.StrictMode>,
  );
}

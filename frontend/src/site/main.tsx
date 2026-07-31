import React from "react";
import ReactDOM from "react-dom/client";
import "@fontsource-variable/space-grotesk/wght.css";

import { AuthProvider } from "../features/auth/AuthContext";
import { I18nProvider } from "../i18n/I18nProvider";
import {
  accountCommunityActionsAllowed,
  sensitiveCloudActionsAllowed,
} from "../security/sensitiveOrigin";
import "../styles.css";
import { SiteApp } from "./SiteApp";
import "./site.css";

const sensitiveCloudActionsEnabled = sensitiveCloudActionsAllowed();
const accountCommunityActionsEnabled = accountCommunityActionsAllowed();

ReactDOM.createRoot(document.getElementById("site-root")!).render(
  <React.StrictMode>
    <I18nProvider>
      <AuthProvider cloudActionsEnabled={accountCommunityActionsEnabled}>
        <SiteApp
          accountCommunityActionsEnabled={accountCommunityActionsEnabled}
          sensitiveCloudActionsEnabled={sensitiveCloudActionsEnabled}
        />
      </AuthProvider>
    </I18nProvider>
  </React.StrictMode>,
);

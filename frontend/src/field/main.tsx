import React from "react";
import ReactDOM from "react-dom/client";

import { AuthProvider } from "../features/auth/AuthContext";
import { I18nProvider } from "../i18n/I18nProvider";
import { EditionThemeProvider } from "../theme/EditionThemeProvider";
import { FieldRoot } from "./FieldRoot";
import "../brand/edition-brand.generated.css";
import "../styles.css";
import "./field.css";

const root = document.getElementById("root");
if (!root) throw new Error("Field root element is missing");

ReactDOM.createRoot(root).render(
  <React.StrictMode>
    <EditionThemeProvider edition="field">
      <I18nProvider>
        <AuthProvider>
          <FieldRoot />
        </AuthProvider>
      </I18nProvider>
    </EditionThemeProvider>
  </React.StrictMode>,
);

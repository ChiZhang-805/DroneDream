import React from "react";
import ReactDOM from "react-dom/client";

import { AuthProvider } from "../features/auth/AuthContext";
import { AppUpdaterProvider } from "../desktop/updaterContext";
import { EditionThemeProvider } from "../theme/EditionThemeProvider";
import { FieldLocaleProvider } from "./FieldLocaleProvider";
import { FieldRoot } from "./FieldRoot";
import "../brand/edition-brand.generated.css";
import "../styles.css";
import "./field.css";

const root = document.getElementById("root");
if (!root) throw new Error("Field root element is missing");

ReactDOM.createRoot(root).render(
  <React.StrictMode>
    <EditionThemeProvider edition="field">
      <FieldLocaleProvider>
        <AuthProvider>
          <AppUpdaterProvider>
            <FieldRoot />
          </AppUpdaterProvider>
        </AuthProvider>
      </FieldLocaleProvider>
    </EditionThemeProvider>
  </React.StrictMode>,
);

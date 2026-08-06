import React from "react";
import ReactDOM from "react-dom/client";

import { AuthProvider } from "../features/auth/AuthContext";
import { EditionThemeProvider } from "../theme/EditionThemeProvider";
import { FieldApp } from "./FieldApp";
import "../brand/edition-brand.generated.css";
import "./field.css";

const root = document.getElementById("root");
if (!root) throw new Error("Field root element is missing");

ReactDOM.createRoot(root).render(
  <React.StrictMode>
    <EditionThemeProvider edition="field">
      <AuthProvider>
        <FieldApp />
      </AuthProvider>
    </EditionThemeProvider>
  </React.StrictMode>,
);

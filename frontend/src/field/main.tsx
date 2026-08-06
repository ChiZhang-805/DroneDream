import React from "react";
import ReactDOM from "react-dom/client";

import { AuthProvider } from "../features/auth/AuthContext";
import { FieldApp } from "./FieldApp";
import "./field.css";

const root = document.getElementById("root");
if (!root) throw new Error("Field root element is missing");

ReactDOM.createRoot(root).render(
  <React.StrictMode>
    <AuthProvider>
      <FieldApp />
    </AuthProvider>
  </React.StrictMode>,
);

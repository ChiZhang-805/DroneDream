import React from "react";
import ReactDOM from "react-dom/client";

import { FieldApp } from "./FieldApp";
import "./field.css";

const root = document.getElementById("root");
if (!root) throw new Error("Field root element is missing");

ReactDOM.createRoot(root).render(
  <React.StrictMode>
    <FieldApp />
  </React.StrictMode>,
);

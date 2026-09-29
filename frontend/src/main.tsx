import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { watchInstallPrompt } from "./pwa/install";
import { watchNotchSide } from "./pwa/notch";
import "./theme/theme.less";

watchInstallPrompt();
watchNotchSide();

const root = document.getElementById("root");
if (!root) throw new Error("Missing #root element");

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

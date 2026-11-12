import React from "react";
import ReactDOM from "react-dom/client";

import App from "./App";

/* Design System CSS */
import "./styles/variables.css";
import "./styles/base.css";
import "./styles/layout.css";
import "./styles/components.css";
import "./styles/pages.css";
import "./styles/animations.css";
import "./styles/splash.css";
import "./styles/theme-light.css";
import "./styles/status-contrast.css";
import "./styles/legibility.css";
import "./styles/digital-human.css";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);

import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "./index.css";

const pathname = window.location.pathname || "";
const base = pathname.startsWith("/economy-manager")
  ? "/economy-manager"
  : pathname.startsWith("/item-manager")
    ? "/item-manager"
    : "/character-manager";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <BrowserRouter basename={base}>
      <App />
    </BrowserRouter>
  </React.StrictMode>
);

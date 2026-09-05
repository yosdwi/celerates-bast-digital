import { createRoot } from "react-dom/client";
import App from "./app/App";
import TalentMobileApp from "./mobile/TalentMobileApp";
import "./styles/global.css";
import "./styles/slice2.css";
import "./styles/slice3.css";
import "./styles/slice4.css";
import "./styles/slice5.css";
import "./styles/slice6.css";
import "./styles/action-pipeline.css";
import "./styles/investigation.css";
import "./styles/talent360-correlation.css";
import "./styles/period-control.css";
import "./styles/workflow.css";
import "./styles/task-evidence.css";
import "./styles/talent-mobile.css";
import "./styles/talent-urls.css";
import "./styles/attendance-gaps.css";

const root = document.getElementById("root");
if (!root) {
  throw new Error("TalentOps root element is missing");
}

const isTalentMobile = window.location.pathname.replace(/\/+$/, "") === "/talent/mobile";
createRoot(root).render(isTalentMobile ? <TalentMobileApp /> : <App />);

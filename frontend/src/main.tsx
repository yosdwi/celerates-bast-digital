import { createRoot } from "react-dom/client";
import App from "./app/App";
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

const root = document.getElementById("root");
if (!root) {
  throw new Error("TalentOps root element is missing");
}

createRoot(root).render(<App />);

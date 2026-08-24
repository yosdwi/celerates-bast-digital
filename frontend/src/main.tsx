import { createRoot } from "react-dom/client";
import App from "./app/App";
import "./styles/global.css";
import "./styles/slice2.css";

const root = document.getElementById("root");
if (!root) {
  throw new Error("TalentOps root element is missing");
}

createRoot(root).render(<App />);

import { createRoot } from "react-dom/client";
import { App } from "./App";
import { Workbench } from "./app/workbench";
import { resolveMode } from "./mode";
import { createServices } from "./services";
import "./styles.css";

// Boot sequence (line 2292): header drops in, then the columns rise; the class goes after 1.4 s.
document.body.classList.add("booting");
setTimeout(() => document.body.classList.remove("booting"), 1400);

// No StrictMode: its double-run effects would replay the one-shot decode animations in development.
void createServices(resolveMode()).then(({ stores, services }) => {
  const workbench = new Workbench(stores, services);
  createRoot(document.getElementById("root")!).render(<App stores={stores} workbench={workbench} />);
  // Live: show the current session's last run, or re-attach to it (a no-op in demo mode).
  void workbench.boot();
});

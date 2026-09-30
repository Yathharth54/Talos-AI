import { useRef, type ReactNode } from "react";
import { useRestartAnimation } from "../../hooks/useRestartAnimation";
import { COPY } from "../../lib/copy";
import { railPercent } from "../../store/runOps";
import type { Run, TabId } from "../../store/types";
import { Banner } from "./Banner";
import { Strip } from "./Strip";
import { Tabs } from "./Tabs";

export type BenchProps = {
  run: Run;
  /** The rail's `running` state (updateRail, line 1053). */
  live: boolean;
  panel: ReactNode;
  onTab(tab: TabId): void;
  onStop(): void;
  onOpenTool(name: string): void;
};

/** The bench for a run (renderBench, lines 1086–1104; sigHtml 1105; setActions 1110–1114). */
export function Bench({ run, live, panel, onTab, onStop, onOpenTool }: BenchProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  useRestartAnimation(panelRef, "panel-in", run.tab);
  const sig = run.sig;
  return (
    <>
      <div className={`rail ${live ? "running" : "done"}`} id="b-rail" aria-hidden="true">
        <i style={{ width: `${railPercent(run)}%` }}></i>
      </div>
      <div className="b-head">
        <div className="meta">
          <span className="label" id="b-label">
            {run.label || ""}
          </span>
          <h1 className="sig" id="b-sig">
            {sig ? (
              <>
                {sig.name}
                <span>
                  ({sig.args}){sig.ret ? ` -> ${sig.ret}` : ""}
                </span>
              </>
            ) : (
              run.title || ""
            )}
          </h1>
        </div>
        <div id="b-act">
          {run.status === "running" || run.status === "waiting" ? (
            <button type="button" className="pill ghost sm" data-action="stop" onClick={onStop}>
              {COPY.bench.stop}
            </button>
          ) : null}
        </div>
      </div>
      <div className="stack" style={{ gap: 16 }}>
        <Strip run={run} />
        <p className="caption" id="b-cap" dangerouslySetInnerHTML={{ __html: run.caption || "" }} />
      </div>
      <div id="b-banner">
        <Banner banner={run.banner} onOpenTool={onOpenTool} />
      </div>
      <div id="b-tabs">
        <Tabs run={run} onSelect={onTab} />
      </div>
      <div id="b-panel" className="stack" ref={panelRef}>
        {panel}
      </div>
    </>
  );
}

import { useRef } from "react";
import { useScramble } from "../../../hooks/useScramble";
import { COPY, fill } from "../../../lib/copy";
import { esc } from "../../../lib/format";
import type { LogLine, LogLn, Run } from "../../../store/types";
import { Earlier } from "./Earlier";
import type { EarlierData } from "./Panel";

type LogPanelProps = { run: Run; isCurrent: boolean; earlier: EarlierData | null; onRun(n: number): void };

/** A plain log line; a fresh one decodes its label (and a gold one its text) as it appears (log(), lines 1286–1289). */
function Ln({ line }: { line: LogLn }) {
  const emRef = useRef<HTMLElement>(null);
  const ltRef = useRef<HTMLSpanElement>(null);
  useScramble(emRef, line.label, 320, { onMount: !!line.fresh });
  useScramble(ltRef, line.text, 480, { onMount: !!line.fresh && line.tone === "g" });
  return (
    <div className={`ln${line.tone ? " " + line.tone : ""}${line.fresh ? " fresh" : ""}`}>
      <em ref={emRef} dangerouslySetInnerHTML={{ __html: esc(line.label) }} />
      <span className="lt" ref={ltRef} dangerouslySetInnerHTML={{ __html: esc(line.text) }} />
      {line.caret ? <span className="caret" aria-hidden="true" style={{ marginLeft: "4px" }}></span> : null}
    </div>
  );
}

/** One log line (logLineHtml, lines 1273–1278). */
function Line({ line }: { line: LogLine }) {
  if (line.kind === "cmd") {
    const text = line.shown != null ? line.text.slice(0, line.shown) : line.text;
    return (
      <>
        <div className="cmd">
          {COPY.log.prompt + text}
          {line.typing ? <span className="caret" aria-hidden="true"></span> : null}
        </div>
        <div className="gap"></div>
      </>
    );
  }
  if (line.kind === "sub") return <div className="ln sub">{line.text}</div>;
  return <Ln line={line} />;
}

/** The run log tab (logPanelHtml, lines 1239–1246). */
export function LogPanel({ run, isCurrent, earlier, onRun }: LogPanelProps) {
  return (
    <div className="log-wrap">
      <div className="stack" style={{ gap: "12px" }}>
        <figure className={`term${run.logTone ? " " + run.logTone : ""}`} id="term">
          <figcaption className="term-cap">
            <span>{isCurrent ? COPY.log.thisRun : fill(COPY.log.runN, { n: run.n })}</span>
            <span id="term-status" className={run.logStatusGold ? "gold" : "muted"}>
              {run.logStatus || ""}
            </span>
          </figcaption>
          <div className="term-body" id="term-body">
            {run.log.map((l, i) => (
              <Line key={l.key ?? i} line={l} />
            ))}
          </div>
        </figure>
        <p className="side-note">{COPY.log.note}</p>
      </div>
      <Earlier data={earlier} onRun={onRun} />
    </div>
  );
}

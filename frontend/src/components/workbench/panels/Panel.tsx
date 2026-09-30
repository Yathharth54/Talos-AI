import { COPY } from "../../../lib/copy";
import type { Run, VaultTool } from "../../../store/types";
import { AttemptsPanel } from "./AttemptsPanel";
import { CallPanel } from "./CallPanel";
import { CodePanel } from "./CodePanel";
import { HistoryPanel } from "./HistoryPanel";
import { LogPanel } from "./LogPanel";
import { TestsPanel } from "./TestsPanel";

/** The earlier-runs list, already filtered and in display order. */
export type EarlierData = { heading: string; runs: Run[] };

export type PanelProps = {
  run: Run;
  isCurrent: boolean;
  tool: VaultTool | undefined;
  earlier: EarlierData | null;
  onAsk(q: string): void;
  onOpenTool(name: string): void;
  onRun(n: number): void;
};

/** earlierHtml()'s list (line 1268): finished runs other than `except`, newest first. */
export function earlierData(runs: Run[], except: Run | null, viewSession: boolean): EarlierData | null {
  const list = runs.filter((r) => r.n !== except?.n && r.status !== "running" && r.status !== "waiting");
  if (!list.length) return null;
  return { heading: viewSession ? COPY.log.inSession : COPY.log.earlier, runs: list.slice().reverse() };
}

/** The selected tab's panel (panelHtml, lines 1156–1167). */
export function Panel({ run, isCurrent, tool, earlier, onAsk, onOpenTool, onRun }: PanelProps) {
  switch (run.tab) {
    case "code":
      return <CodePanel code={run.code} codeScroll={run.codeScroll} />;
    case "tests":
      return <TestsPanel runN={run.n} tests={run.tests} smoke={run.smoke} attempts={run.attempts} />;
    case "attempts":
      return <AttemptsPanel attempts={run.attempts} />;
    case "call":
      return <CallPanel call={run.call} onAsk={onAsk} onOpenTool={onOpenTool} />;
    case "history":
      return <HistoryPanel tool={tool} />;
    case "log":
      return <LogPanel run={run} isCurrent={isCurrent} earlier={earlier} onRun={onRun} />;
    // "answer": the reference never sets answerPanel.
    default:
      return null;
  }
}

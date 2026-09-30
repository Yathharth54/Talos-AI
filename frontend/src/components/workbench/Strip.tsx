import { useRef, useState } from "react";
import { useRestartAnimation } from "../../hooks/useRestartAnimation";
import { COPY } from "../../lib/copy";
import { STRIPS } from "../../store/runOps";
import type { Run } from "../../store/types";
import { XIcon } from "../icons";

type StripLinkProps = { lk: string; swap: boolean; lit: boolean; retrying: boolean; flows: number; mountFlows: number };

/** One link of the strip (stripHtml, line 1017; flow() line 1033; retrying() line 1040). */
function StripLink({ lk, swap, lit, retrying, flows, mountFlows }: StripLinkProps) {
  const ref = useRef<HTMLLIElement>(null);
  useRestartAnimation(ref, "flow", flows);
  // The reference adds "flow" on each flow() and keeps it until the bench is re-rendered (line 1038).
  const flowed = flows > mountFlows;
  const cls = `link${swap ? " swap" : ""}${lit ? " lit" : ""}${flowed ? " flow" : ""}${swap && retrying ? " retrying" : ""}`;
  return <li ref={ref} className={cls} data-link={lk} aria-hidden="true"></li>;
}

/** The graph strip (stripHtml, lines 1007–1019, inside renderBench's <ol>, line 1097). */
export function Strip({ run }: { run: Run }) {
  const mountFlows = useRef(run.flows ?? {});
  // stripHtml() never emits "retrying"; only a retrying() call after the render shows it (line 1040).
  const [staleRetry, setStaleRetry] = useState(!!run.retrying);
  if (staleRetry && !run.retrying) setStaleRetry(false);
  const retrying = !!run.retrying && !staleRetry;
  const items = STRIPS[run.strip];
  return (
    <ol className="strip" id="b-strip" aria-label={COPY.bench.graph}>
      {items.map(([key], i) => {
        const n = run.nodes[key];
        if (!n) return null;
        const next = items[i + 1]?.[0];
        const lk = next ? `${key}-${next}` : "";
        return [
          <li key={key} className={`node ${n.state}`} data-node={key} aria-current={n.state === "active" ? "step" : undefined}>
            {n.state === "fail" ? <XIcon /> : null}
            <span className="nl">{n.label}</span>
            {n.llm ? <span className="pip" aria-hidden="true"></span> : null}
          </li>,
          next ? (
            <StripLink
              key={lk}
              lk={lk}
              swap={key === "forger" && next === "tester"}
              lit={!!run.links[lk]}
              retrying={retrying}
              flows={run.flows?.[lk] ?? 0}
              mountFlows={mountFlows.current[lk] ?? 0}
            />
          ) : null,
        ];
      })}
    </ol>
  );
}

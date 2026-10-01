import type { EarlierData } from "./Panel";

/** The earlier-runs list under the run log (earlierHtml, lines 1268–1272). */
export function Earlier({ data, onRun }: { data: EarlierData | null; onRun(n: number): void }) {
  if (!data) return null;
  return (
    <div className="earlier">
      <h2>{data.heading}</h2>
      {data.runs.map((r) => (
        <button key={r.n} type="button" data-run={r.n} onClick={() => onRun(r.n)}>
          <span className="q">{r.query}</span>
          <span className={`s${r.summaryGold ? " gold" : ""}`}>{r.summary || ""}</span>
        </button>
      ))}
    </div>
  );
}

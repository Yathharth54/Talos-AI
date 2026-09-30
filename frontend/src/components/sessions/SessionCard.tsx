import { COPY, fill } from "../../lib/copy";
import { fmtClock } from "../../lib/format";
import type { Run, SessionRec } from "../../store/types";

export interface SessionCardProps {
  session: SessionRec;
  runs: Run[];
  index: number;
  isCur: boolean;
  onOpen(id: string): void;
}

/** One session card: sessCard (line 2270). */
export function SessionCard({ session, runs, index, isCur, onOpen }: SessionCardProps) {
  const forged = [...new Set(runs.filter((r) => r.forged).map((r) => r.toolUsed))] as string[];
  const reused = ([...new Set(runs.filter((r) => !r.forged && r.toolUsed && !r.failed).map((r) => r.toolUsed))] as string[]).filter((n) => !forged.includes(n));
  const t = COPY.sessions;
  const stats = `${runs.length} ${runs.length === 1 ? t.run : t.runs}${forged.length ? fill(t.forgedCount, { n: forged.length }) : ""}`;
  return (
    <article className="sess" style={{ animationDelay: `${index * 60}ms` }}>
      <div className="when">
        <b>{fmtClock(session.started)}</b>
        <span>{stats}</span>
        {isCur ? <span className="live">{t.now}</span> : null}
      </div>
      <div className="body">
        <h3>{session.name}</h3>
        {runs.length ? (
          <ol>
            {runs.slice(0, 3).map((r) => (
              <li key={r.id}>
                <i className={r.failed ? "failed" : r.forged ? "forged" : r.toolUsed ? "reused" : ""} aria-hidden="true"></i>
                <span>{r.query}</span>
              </li>
            ))}
            {runs.length > 3 ? (
              <li className="muted" style={{ paddingLeft: 17 }}>
                {fill(t.more, { n: runs.length - 3 })}
              </li>
            ) : null}
          </ol>
        ) : (
          <p className="sess-empty" style={{ margin: 0 }}>
            {t.empty}
          </p>
        )}
        {forged.length || reused.length ? (
          <div className="tools">
            {forged.map((n) => (
              <span className="forged" key={`f-${n}`}>
                {n}
              </span>
            ))}
            {reused.map((n) => (
              <span key={`r-${n}`}>{n}</span>
            ))}
          </div>
        ) : null}
      </div>
      <button type="button" className="pill ghost sm" data-open-session={session.id} onClick={() => onOpen(session.id)}>
        {isCur ? t.cont : t.open}
      </button>
    </article>
  );
}

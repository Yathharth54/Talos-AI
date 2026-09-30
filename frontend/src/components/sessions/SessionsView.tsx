import { COPY } from "../../lib/copy";
import { fmtDay, sameDay } from "../../lib/format";
import type { Run, SessionRec } from "../../store/types";
import { SessionCard } from "./SessionCard";

export interface SessionsViewProps {
  sessions: SessionRec[];
  runsById: Record<string, Run>;
  curId: string;
  onOpen(id: string): void;
}

/** The sessions list grouped by day: renderSessions (line 2257). Renders the content of `.sessions-in`. */
export function SessionsView({ sessions, runsById, curId, onOpen }: SessionsViewProps) {
  const runsOf = (s: SessionRec): Run[] => s.runIds.map((id) => runsById[id]).filter((r): r is Run => !!r);
  const list = sessions
    .filter((x) => x.runIds.length || x.id === curId)
    .slice()
    .sort((a, b) => b.started.localeCompare(a.started));
  const groups: { label: string; items: SessionRec[] }[] = [];
  list.forEach((x) => {
    const label = sameDay(x.started) ? COPY.sessions.today : fmtDay(x.started);
    let g = groups.find((y) => y.label === label);
    if (!g) {
      g = { label, items: [] };
      groups.push(g);
    }
    g.items.push(x);
  });
  let k = 0;
  return (
    <>
      <div>
        <h1>{COPY.sessions.title}</h1>
        <p className="lede">{COPY.sessions.lede}</p>
      </div>
      {groups.map((g) => (
        <section className="day" aria-label={g.label} key={g.label}>
          <h2>{g.label}</h2>
          {g.items.map((x) => (
            <SessionCard key={x.id} session={x} runs={runsOf(x)} index={k++} isCur={x.id === curId} onOpen={onOpen} />
          ))}
        </section>
      ))}
    </>
  );
}

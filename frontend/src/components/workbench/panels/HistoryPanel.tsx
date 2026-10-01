import { COPY, fill } from "../../../lib/copy";
import { fmtTime } from "../../../lib/format";
import type { VaultTool } from "../../../store/types";

/** The history panel (historyHtml, lines 1230–1234). */
export function HistoryPanel({ tool: t }: { tool: VaultTool | undefined }) {
  if (!t) return <p className="muted">{COPY.history.gone}</p>;
  return (
    <dl className="dl">
      <div>
        <dt>{COPY.history.forged}</dt>
        <dd>{fmtTime(t.created)}</dd>
      </div>
      <div>
        <dt>{COPY.history.lastUsed}</dt>
        <dd>{fmtTime(t.last)}</dd>
      </div>
      <div>
        <dt>{COPY.history.uses}</dt>
        <dd>{t.uses}</dd>
      </div>
      <div>
        <dt>{COPY.history.failures}</dt>
        <dd>{fill(COPY.history.failuresValue, { f: t.fails, s: t.streak })}</dd>
      </div>
      {t.lastFail ? (
        <div className="full">
          <dt>{COPY.history.lastFailure}</dt>
          <dd className="mono">{t.lastFail}</dd>
        </div>
      ) : null}
    </dl>
  );
}

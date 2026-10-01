import { Fragment, type ReactNode } from "react";
import { COPY, fill } from "../../../lib/copy";
import { PRUNE_AT } from "../../../lib/routing";
import type { CallState } from "../../../store/types";

type CallPanelProps = { call: CallState | undefined; onAsk(q: string): void; onOpenTool(name: string): void };

/** The call panel (callHtml, lines 1206–1229). */
export function CallPanel({ call: c, onAsk, onOpenTool }: CallPanelProps) {
  if (!c) return null;
  let args: ReactNode[];
  if (c.noArgs) {
    args = [
      <Fragment key="none">
        <dt></dt>
        <dd className="muted">{COPY.call.none}</dd>
      </Fragment>,
    ];
  } else {
    args = c.args.slice(0, c.shownArgs == null ? c.args.length : c.shownArgs).map(([k, v, bad], i) => (
      <Fragment key={i}>
        <dt>{k}</dt>
        <dd>{bad ? <span className="bad">{v}</span> : v}</dd>
      </Fragment>
    ));
  }
  let res: ReactNode;
  if (c.error) {
    res = (
      <figure className="fig alert">
        <figcaption className="fig-cap">
          <span>{COPY.call.errorCap}</span>
          <span className="r">{c.when || ""}</span>
        </figcaption>
        <div className="result small mono">{c.error}</div>
      </figure>
    );
  } else if (c.result != null) {
    res = (
      <figure className="fig">
        <figcaption className="fig-cap">
          <span>{c.resultCap || COPY.call.result}</span>
          <span className="r">{c.resultType || ""}</span>
        </figcaption>
        <div className={`result${c.smallResult ? " small" : ""}`}>{c.result}</div>
      </figure>
    );
  } else {
    res = (
      <figure className="fig">
        <figcaption className="fig-cap">
          <span>{COPY.call.result}</span>
          <span className="r"></span>
        </figcaption>
        <div className="result small muted" dangerouslySetInnerHTML={{ __html: c.pending || COPY.call.waiting }} />
      </figure>
    );
  }
  const r = c.record;
  const h = c.health;
  return (
    <>
      <div className="grid2">
        <figure className="fig">
          <figcaption className="fig-cap">
            <span>{COPY.call.args}</span>
            <span className="r">{c.argsCap || COPY.call.argsCap}</span>
          </figcaption>
          <dl className="args">
            {args.length ? (
              args
            ) : (
              <>
                <dt></dt>
                <dd className="muted">
                  {COPY.call.resolving}
                  <span className="caret" aria-hidden="true"></span>
                </dd>
              </>
            )}
          </dl>
        </figure>
        {res}
      </div>
      {r ? (
        <section className="record" aria-label={COPY.call.record}>
          <div>
            <span className="k">{COPY.call.forged}</span>
            <span>{r.forged}</span>
          </div>
          <div className="hot">
            <span className="k">{COPY.call.uses}</span>
            <span>{r.uses}</span>
          </div>
          <div>
            <span className="k">{COPY.call.failures}</span>
            <span>{r.fails}</span>
          </div>
        </section>
      ) : null}
      {h ? (
        <section className="health" aria-label={COPY.call.health}>
          <h3>{COPY.call.health}</h3>
          <div className="row">
            <div className="meter" role="img" aria-label={fill(COPY.call.meter, { s: h.streak, p: PRUNE_AT })}>
              {Array.from({ length: PRUNE_AT }, (_, i) => (
                <span key={i} className={i < h.streak ? "on" : ""}></span>
              ))}
            </div>
            <span>{fill(h.streak === 1 ? COPY.call.streakOne : COPY.call.streakMany, { s: h.streak })}</span>
          </div>
          <p dangerouslySetInnerHTML={{ __html: h.text }} />
          {h.retry ? (
            <div className="actions">
              <button type="button" className="pill solid" data-ask={h.retry.q} onClick={() => h.retry && onAsk(h.retry.q)}>
                {h.retry.label}
              </button>
              <a className="pill ghost" href="#vault" data-open-tool={h.tool} onClick={() => onOpenTool(h.tool)}>
                {COPY.call.openInVault}
              </a>
            </div>
          ) : null}
        </section>
      ) : null}
    </>
  );
}

import { useRef } from "react";
import { COPY, fill } from "../../lib/copy";
import { fmtTime } from "../../lib/format";
import { PRUNE_AT } from "../../lib/routing";
import { useRestartAnimation } from "../../hooks/useRestartAnimation";
import type { VaultTool } from "../../store/types";
import { CodeRows } from "./CodeRows";
import { bareZeros } from "../../lib/style";

export interface VaultDetailProps {
  tool: VaultTool | undefined;
  source: string[] | null;
  confirmRemove: string | null;
  onRead(name: string): void;
  onUse(name: string): void;
  onRemove(name: string): void;
}

/** renderDetail (lines 1984–2013). The `swap` class appears with the first tool shown (kept from then on) and is replayed when the selection changes. */
export function VaultDetail({ tool: t, source: src, confirmRemove, onRead, onUse, onRemove }: VaultDetailProps) {
  const ref = useRef<HTMLElement>(null);
  useRestartAnimation(ref, "swap", t?.name ?? null);
  // The reference adds `swap` the first time a tool is shown and never removes it (it only replays it).
  const shown = useRef(false);
  if (t) shown.current = true;
  return (
    <aside className={`v-detail${shown.current ? " swap" : ""}`} id="v-detail" aria-label={COPY.vault.detailAria} ref={ref}>
      {!t ? (
        <p className="muted">{COPY.vault.pick}</p>
      ) : (
        <>
          <div className="stack" style={{ gap: "8px" }}>
            <h2>{t.name}</h2>
            <p className="desc">{t.desc}</p>
          </div>
          <div className="sigbox">
            {t.name}({t.args}){t.ret ? " -> " + t.ret : ""}
          </div>
          <ul className="kws" aria-label={COPY.vault.keywords}>
            {t.kw.map((k, i) => (
              <li key={i}>{k}</li>
            ))}
          </ul>
          <dl className="dl">
            <div>
              <dt>{COPY.vault.forged}</dt>
              <dd>{fmtTime(t.created)}</dd>
            </div>
            <div>
              <dt>{COPY.vault.lastUsed}</dt>
              <dd>{t.last ? fmtTime(t.last) : COPY.vault.notYet}</dd>
            </div>
            <div>
              <dt>{COPY.vault.uses}</dt>
              <dd>{t.uses}</dd>
            </div>
            <div>
              <dt>{COPY.vault.failures}</dt>
              <dd>{t.fails ? fill(COPY.vault.failuresValue, { f: t.fails, s: t.streak }) : COPY.vault.none}</dd>
            </div>
            {t.lastFail ? (
              <div className="full">
                <dt>
                  {COPY.vault.lastFailure}
                  {t.lastFailAt ? ", " + fmtTime(t.lastFailAt) : ""}
                </dt>
                <dd className="mono">{t.lastFail}</dd>
              </div>
            ) : null}
            <div className="full">
              <dt>{COPY.vault.file}</dt>
              <dd className="mono">{fill(COPY.vault.filePath, { name: t.name })}</dd>
            </div>
            <div className="full">
              <dt>{COPY.vault.reachesWeb}</dt>
              <dd>{t.web ? COPY.vault.webYes : COPY.vault.webNo}</dd>
            </div>
          </dl>
          <section className="health" aria-label={COPY.vault.healthAria}>
            <div className="row">
              <div className="meter" role="img" aria-label={fill(COPY.call.meter, { s: t.streak, p: PRUNE_AT })}>
                {Array.from({ length: PRUNE_AT }, (_, i) => (
                  <span key={i} className={i < t.streak ? "on" : ""}></span>
                ))}
              </div>
              <span style={{ fontSize: "14px" }}>{t.streak ? COPY.vault.healthOne : COPY.vault.healthOk}</span>
            </div>
            <p style={{ fontSize: "13px" }}>{COPY.vault.healthNote}</p>
          </section>
          {src ? (
            <figure className="fig code-read">
              <figcaption className="fig-cap">
                <span className="meta">
                  <span className="mono">{fill(COPY.vault.previewName, { name: t.name })}</span>
                  <span>{fill(COPY.vault.previewSub, { n: src.length })}</span>
                </span>
                <button type="button" className="pill ghost sm" data-read-src={t.name} onClick={() => onRead(t.name)}>
                  {COPY.vault.read}
                </button>
              </figcaption>
              <div className="code-fade">
                <div className="code-body" tabIndex={0} aria-label={COPY.vault.previewAria}>
                  <CodeRows lines={src} />
                </div>
              </div>
            </figure>
          ) : (
            <p className="muted" style={{ margin: 0, fontSize: 13 }} ref={bareZeros}>
              {fill(COPY.vault.noSource, { name: t.name })}
            </p>
          )}
          <div className="actions">
            <button type="button" className="pill solid" data-use-tool={t.name} onClick={() => onUse(t.name)}>
              {COPY.vault.use}
            </button>
            <button
              type="button"
              className="pill ghost"
              data-remove-tool={t.name}
              data-confirm={confirmRemove === t.name ? "1" : undefined}
              onClick={() => onRemove(t.name)}
            >
              {confirmRemove === t.name ? fill(COPY.vault.confirm, { name: t.name }) : COPY.vault.remove}
            </button>
          </div>
        </>
      )}
    </aside>
  );
}

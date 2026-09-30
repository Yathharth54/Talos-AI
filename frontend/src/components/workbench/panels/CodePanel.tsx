import { useLayoutEffect, useRef } from "react";
import { COPY } from "../../../lib/copy";
import { highlight } from "../../../lib/highlight";
import type { CodeState, Run } from "../../../store/types";

/** The code panel (codeHtml, lines 1168–1180; its scroll in renderPanel, line 1154). */
export function CodePanel({ code, codeScroll }: { code: CodeState | undefined; codeScroll: Run["codeScroll"] }) {
  const bodyRef = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const cb = bodyRef.current;
    if (!cb) return;
    if (codeScroll === "bottom") cb.scrollTop = cb.scrollHeight;
    if (typeof codeScroll === "number") {
      const row = cb.querySelector<HTMLElement>(`[data-ln="${codeScroll}"]`);
      if (row) cb.scrollTop = row.offsetTop - cb.clientHeight / 2;
    }
  });
  if (!code) return null;
  const hl = highlight(code.lines).slice(0, code.shown);
  const lines = code.lines.slice(0, code.shown);
  return (
    <>
      <figure className="fig code">
        <figcaption className="fig-cap">
          <span className="mono">{code.file}</span>
          <span className="r">{code.cap}</span>
        </figcaption>
        <div className="code-body" tabIndex={0} aria-label={COPY.code.aria} ref={bodyRef}>
          {lines.map((_, i) => {
            const n = i + 1;
            const changed = code.changed === n ? " changed" + (code.flash ? " flash" : "") : "";
            return (
              <div key={n} className={`code-row${changed}`} data-ln={n}>
                <span className="ln">{n}</span>
                <span className="tx" dangerouslySetInnerHTML={{ __html: hl[i] || " " }} />
              </div>
            );
          })}
          {code.shown < code.lines.length ? (
            <div className="code-row">
              <span className="ln"></span>
              <span className="tx">
                <span className="caret gold" aria-hidden="true"></span>
              </span>
            </div>
          ) : null}
        </div>
      </figure>
      {code.note ? <p className="code-note" dangerouslySetInnerHTML={{ __html: '<i aria-hidden="true"></i>' + code.note }} /> : null}
    </>
  );
}

import { useLayoutEffect, useMemo, useRef, useState } from "react";
import { COPY } from "../../lib/copy";
import { wrapWordsHtml } from "../../lib/motion";
import { SUGGESTIONS } from "../../demo/data";
import type { Message as Msg, TalosMessage } from "../../store/types";

export interface MessageProps {
  msg: Msg;
  /** Dim earlier messages of the live session (`.past`); an old session opens without it (line 2186). */
  showPast: boolean;
  viewingN: number | null;
  onRun(n: number): void;
  onSuggest(i: number): void;
}

/** One `.msg` (addYou 936–941, addTalos 942–970, sessionHtml 2229–2231). */
export function Message({ msg, showPast, viewingN, onRun, onSuggest }: MessageProps) {
  if (msg.kind === "you") {
    return (
      <div className={`msg you${msg.past && showPast ? " past" : ""}`}>
        <span className="who">{COPY.convo.you}</span>
        <p>{msg.text}</p>
      </div>
    );
  }
  return (
    <div className={`msg talos${msg.past && showPast ? " past" : ""}`}>
      <span className="who">{COPY.convo.talos}</span>
      {msg.html == null && msg.stopNote == null ? (
        <span className="thinking">
          <span className="orb" aria-hidden="true">
            <i></i>
          </span>
          {/* status() replaces the element (line 949), so a new status restarts its fade. */}
          <span className="tt" key={msg.status ?? ""}>
            {msg.status ?? COPY.convo.thinking}
          </span>
        </span>
      ) : null}
      {msg.html != null ? msg.wrap ? <Answer html={msg.html} wordsOn={msg.wordsOn} /> : <p dangerouslySetInnerHTML={{ __html: msg.html }} /> : null}
      {msg.note != null ? <p className="note" dangerouslySetInnerHTML={{ __html: msg.note }} /> : null}
      {msg.chips.map((c, i) => (
        <span key={i} className={`chip ${c.kind}`}>
          <i aria-hidden="true"></i>
          {c.text}
        </span>
      ))}
      {msg.suggest ? (
        <div className="suggest-inline">
          {SUGGESTIONS.map((s, i) => (
            <button key={i} type="button" data-suggest={i} onClick={() => onSuggest(i)}>
              {s.q}
            </button>
          ))}
        </div>
      ) : null}
      {msg.stopNote != null ? <p className="note">{msg.stopNote}</p> : null}
      {msg.runLink ? <RunLink msg={msg} viewingN={viewingN} onRun={onRun} /> : null}
    </div>
  );
}

function RunLink({ msg, viewingN, onRun }: { msg: TalosMessage; viewingN: number | null; onRun(n: number): void }) {
  return (
    <button type="button" className="run-link" data-run={msg.runN} aria-current={viewingN === msg.runN ? "true" : "false"} onClick={() => onRun(msg.runN)}>
      {COPY.convo.viewRun}
    </button>
  );
}

/**
 * The answer paragraph (say(), lines 950–960). The words are wrapped once; later `wordsOn` changes add
 * `on` to the same `.wd` elements, so their CSS transition runs as `classList.add("on")` does.
 */
function Answer({ html, wordsOn }: { html: string; wordsOn: number }) {
  const ref = useRef<HTMLParagraphElement>(null);
  const [initialOn] = useState(wordsOn);
  // Only a new answer re-wraps; the words switching on is done in place below.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const __html = useMemo(() => wrapWordsHtml(html, initialOn).html, [html]);
  useLayoutEffect(() => {
    ref.current?.querySelectorAll(".wd").forEach((w, i) => {
      if (i < wordsOn) w.classList.add("on");
    });
  }, [wordsOn, __html]);
  return <p ref={ref} dangerouslySetInnerHTML={{ __html }} />;
}

import { useLayoutEffect, useRef } from "react";
import { COPY, fill } from "../../lib/copy";
import { esc, fmtTime } from "../../lib/format";
import { scramble } from "../../lib/motion";
import type { Message as Msg } from "../../store/types";
import { Composer, type ComposerProps } from "./Composer";
import { Message } from "./Message";

export interface ConversationProps {
  title: string;
  animateTitle: boolean;
  readOnly: { name: string; started: string } | null;
  messages: Msg[];
  empty: boolean;
  busy: boolean;
  viewingN: number | null;
  live: string;
  composer: ComposerProps;
  onNew(): void;
  onBack(): void;
  onRun(n: number): void;
  onSuggest(i: number): void;
}

/** What a message shows: a change means content was added to it, so the list scrolls. */
function contentSig(m: Msg | undefined): string {
  if (!m) return "";
  if (m.kind === "you") return m.key;
  return JSON.stringify([m.key, m.status, m.html, m.wordsOn, m.note, m.chips.length, m.suggest, m.stopNote, m.runLink]);
}

/** The conversation column (lines 630–646; renderEmptyConvo 987–989, openSession 2178–2192, updateComposer 1507–1514). */
export function Conversation(props: ConversationProps) {
  const { title, animateTitle, readOnly, messages, empty, busy, viewingN, live, composer } = props;
  const titleRef = useRef<HTMLSpanElement>(null);
  const msgsRef = useRef<HTMLDivElement>(null);

  // setTitle(name, animate) (line 2168): only a title change decodes, and only when asked. The effect
  // returns no cleanup, because a cancelled decode restores its own text after React has set the new one.
  const titleMounted = useRef(false);
  const cancelTitle = useRef<(() => void) | null>(null);
  useLayoutEffect(() => {
    const first = !titleMounted.current;
    titleMounted.current = true;
    if (first) return;
    cancelTitle.current?.();
    cancelTitle.current = null;
    const el = titleRef.current;
    if (!el) return;
    el.textContent = title;
    if (animateTitle) cancelTitle.current = scramble(el, title, 600);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [title]);
  useLayoutEffect(() => () => cancelTitle.current?.(), []);

  // scrollMsgs() (line 971) runs only when content is added (addYou, addTalos, status, say, chip, append)
  // and on Back to now (line 2202); typing and markRunLinks() never scroll. An old session opens at the top (line 2191).
  const openedKey = readOnly ? `${readOnly.name}\u0000${readOnly.started}` : null;
  const contentKey = empty ? "" : `${messages.length}\u0000${contentSig(messages[messages.length - 1])}`;
  const last = useRef<{ opened: string | null; content: string } | null>(null);
  useLayoutEffect(() => {
    const el = msgsRef.current;
    const prev = last.current;
    last.current = { opened: openedKey, content: contentKey };
    if (!el || !prev) return;
    if (openedKey !== prev.opened) el.scrollTop = openedKey == null ? el.scrollHeight : 0;
    else if (openedKey == null && contentKey !== prev.content) el.scrollTop = el.scrollHeight;
  }, [openedKey, contentKey]);

  return (
    <section className="col convo" aria-label={COPY.convo.aria}>
      <div className="convo-head">
        <h2 id="session-name">
          <span className="scr" id="session-title" ref={titleRef} dangerouslySetInnerHTML={{ __html: esc(title) }} />
        </h2>
        <button type="button" className="pill ghost sm" id="new-session" hidden={!!readOnly} disabled={busy} onClick={props.onNew}>
          {COPY.convo.newSession}
        </button>
        <button type="button" className="pill ghost sm" id="back-session" hidden={!readOnly} onClick={props.onBack}>
          {COPY.convo.backToNow}
        </button>
      </div>
      <div className="msgs" id="msgs" ref={msgsRef}>
        {empty ? (
          <p className="empty-convo">{COPY.convo.empty}</p>
        ) : (
          <>
            {readOnly ? (
              <p className="viewing-note">
                <span>{fill(COPY.convo.readOnly, { name: readOnly.name, time: fmtTime(readOnly.started) })}</span>
              </p>
            ) : null}
            {messages.map((m) => (
              <Message key={m.key} msg={m} showPast={!readOnly} viewingN={viewingN} onRun={props.onRun} onSuggest={props.onSuggest} />
            ))}
          </>
        )}
      </div>
      <div className="sr" aria-live="polite" id="live">
        {live}
      </div>
      <Composer {...composer} />
    </section>
  );
}

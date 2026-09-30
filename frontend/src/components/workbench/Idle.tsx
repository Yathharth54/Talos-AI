import { useRef, useState } from "react";
import { SUGGESTIONS } from "../../demo/data";
import { useCountUp } from "../../hooks/useCountUp";
import { useScramble } from "../../hooks/useScramble";
import { COPY, fill } from "../../lib/copy";
import { esc } from "../../lib/format";

export type IdleProps = {
  count: number;
  weatherKeySet: boolean;
  askExec: boolean;
  onSuggest(i: number): void;
  /** Live mode: how many of the server's keys are set. Absent in demo mode. */
  keys?: { set: number; total: number };
};

/**
 * The idle bench (renderIdle, lines 1060–1078). The reference writes it once per renderIdle() and
 * never updates it in place (showView's renderSideIdle() is empty), so a change made in Settings or
 * the Vault shows only when the idle bench is next drawn. The parent keys this component by that
 * draw, so the values are taken at mount.
 */
export function Idle(props: IdleProps) {
  const [{ count, weatherKeySet, askExec, keys }] = useState(() => props);
  const { onSuggest } = props;
  const headRef = useRef<HTMLHeadingElement>(null);
  const countRef = useRef<HTMLSpanElement>(null);
  useScramble(headRef, COPY.idle.heading, 1000, { onMount: true });
  useCountUp(countRef, count);
  return (
    <div className="idle">
      <div className="art-wrap">
        <span className="orbit o1" aria-hidden="true"></span>
        <span className="orbit o2" aria-hidden="true"></span>
        <img className="art" src="assets/hero-mark.webp" alt="" width="1200" height="480" />
        <span className="scan" aria-hidden="true"></span>
      </div>
      <h1 id="idle-h" ref={headRef} dangerouslySetInnerHTML={{ __html: esc(COPY.idle.heading) }} />
      <p className="lede">
        <span id="idle-count" ref={countRef} dangerouslySetInnerHTML={{ __html: String(count) }} />
        {COPY.idle.lede}
      </p>
      <div className="try-wrap">
        <h2>{COPY.idle.tryHeading}</h2>
        <div className="try-grid">
          {SUGGESTIONS.map((s, i) => (
            <button key={i} type="button" className="try" data-suggest={i} onClick={() => onSuggest(i)}>
              <span className="q">{s.q}</span>
              <span className={`what${s.forge ? " gold" : ""}`}>
                {s.forge ? <i aria-hidden="true"></i> : null}
                {s.what}
              </span>
            </button>
          ))}
        </div>
        <p className="setup-line">
          {fill(COPY.idle.setup, {
            keys: keys ? fill(COPY.idle.keysOfTotal, keys) : weatherKeySet ? COPY.idle.keysWithWeather : COPY.idle.keysWithout,
            state: askExec ? COPY.idle.on : COPY.idle.off,
          })}
          <a href="#settings">{COPY.idle.settings}</a>
        </p>
      </div>
    </div>
  );
}

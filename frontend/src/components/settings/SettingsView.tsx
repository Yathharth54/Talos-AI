import { useRef } from "react";
import { COPY, fill } from "../../lib/copy";
import { PRUNE_AT } from "../../lib/routing";
import type { LiveSettings } from "../../store/types";

export interface SettingsViewProps {
  askExec: boolean;
  env: Record<string, string>;
  model: string;
  onToggleAsk(): void;
  /** Live mode: the key rows and facts come from GET /api/settings. Absent in demo mode. */
  live?: LiveSettings;
}

/** The settings page: renderSettings (line 2043). Renders the content of `.settings-in`. */
export function SettingsView({ askExec, env, model, onToggleAsk, live }: SettingsViewProps) {
  const t = COPY.settings;
  const swRef = useRef<HTMLButtonElement>(null);
  const weather = !!env.OPENWEATHERMAP_API_KEY;
  const desc = t.keyDesc as Record<string, string | undefined>;
  const fixed: [string, boolean, string][] = [
    ["OPENROUTER_API_KEY", true, t.keyDesc.OPENROUTER_API_KEY],
    ["TAVILY_API_KEY", true, t.keyDesc.TAVILY_API_KEY],
    ["JINA_API_KEY", false, t.keyDesc.JINA_API_KEY],
    ["LANGSMITH_API_KEY", false, t.keyDesc.LANGSMITH_API_KEY],
    ["OPENWEATHERMAP_API_KEY", weather, weather ? t.keyDesc.savedByHuman : t.keyDesc.askedWhenNeeded],
  ];
  const keys: [string, boolean, string][] = live
    ? live.keys.map((k) => [k.name, k.set, desc[k.name] ?? t.keyDesc.savedByHuman])
    : fixed;
  return (
    <>
      <h1>{t.title}</h1>
      <section aria-labelledby="set-safety">
        <h2 id="set-safety">{t.safety}</h2>
        <div className="switch-row">
          <div>
            <span id="ask-lbl">{t.ask}</span>
            <p>
              {t.askA}
              <span className="mono">{t.askPython}</span>
              {t.askB}
              <span className="mono">{t.askShell}</span>
              {t.askC}
              <span className="mono">{t.askVar}</span>.
            </p>
          </div>
          <button
            type="button"
            className="switch"
            role="switch"
            aria-checked={String(askExec) as "true" | "false"}
            aria-labelledby="ask-lbl"
            id="ask-switch"
            ref={swRef}
            onClick={() => {
              onToggleAsk();
              swRef.current?.focus();
            }}
          ></button>
        </div>
      </section>
      <section aria-labelledby="set-keys" className="setup">
        <h2 id="set-keys">{t.keys}</h2>
        <ul>
          {keys.map(([k, ok, d]) => (
            <li key={k}>
              <div>
                <span className="mono" style={{ fontSize: 13 }}>
                  {k}
                </span>
                <span className="d">{d}</span>
              </div>
              <span className={ok ? "" : "muted"}>{ok ? t.set : t.notSet}</span>
            </li>
          ))}
        </ul>
      </section>
      <section aria-labelledby="set-forge">
        <h2 id="set-forge">{t.forging}</h2>
        <dl className="facts">
          <div>
            <dt>{t.model}</dt>
            <dd className="mono" style={{ fontSize: 13 }}>
              {model}
            </dd>
          </div>
          <div>
            <dt>{t.retries}</dt>
            <dd>{live ? String(live.forgeRetries) : "3"}</dd>
          </div>
          <div>
            <dt>{t.testLimit}</dt>
            <dd>{live ? fill(t.secondsValue, { n: live.testTimeoutS }) : t.testLimitValue}</dd>
          </div>
          <div>
            <dt>{t.modelLimit}</dt>
            <dd>{live ? fill(t.secondsValue, { n: Math.round(live.llmTimeoutS) }) : t.modelLimitValue}</dd>
          </div>
          <div>
            <dt>{t.pruneAfter}</dt>
            <dd>{fill(t.pruneValue, { n: live ? live.pruneAfter : PRUNE_AT })}</dd>
          </div>
        </dl>
        <p className="side-note">{t.note}</p>
      </section>
    </>
  );
}

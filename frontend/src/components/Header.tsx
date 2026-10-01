import { COPY } from "../lib/copy";
import type { View } from "../store/types";
import { DemoControls } from "./DemoControls";
import { GitHubIcon } from "./icons";

export type HeaderProps = {
  mode: "demo" | "live";
  busy: boolean;
  badge: boolean;
  view: View;
  model: string;
  popOpen: boolean;
  speed: number;
  onTogglePop(open?: boolean): void;
  onSpeed(speed: number): void;
  onReset(): void;
};

const NAV: ReadonlyArray<readonly [View, string]> = [
  ["workbench", COPY.nav.workbench],
  ["vault", COPY.nav.vault],
  ["sessions", COPY.nav.sessions],
  ["settings", COPY.nav.settings],
];

/** The top bar (reference lines 596-625). */
export function Header({ mode, busy, badge, view, model, popOpen, speed, onTogglePop, onSpeed, onReset }: HeaderProps) {
  return (
    <header className="top">
      <a className={busy ? "brand busy" : "brand"} id="brand" href="#workbench" aria-label={COPY.brand.aria}>
        <span className="disc-wrap">
          <span className="disc">
            <img src="assets/apple-touch-icon.png" alt="" width="36" height="36" />
          </span>
          <span className="ring" aria-hidden="true"></span>
        </span>
        <span className="word">{COPY.brand.word}</span>
      </a>
      <nav className="nav" aria-label={COPY.nav.aria}>
        {NAV.map(([v, label]) => (
          <a key={v} href={`#${v}`} data-view={v} aria-current={view === v ? "page" : undefined}>
            {label}
            {v === "vault" && <span className="badge" id="vault-badge" hidden={!badge}></span>}
          </a>
        ))}
      </nav>
      <div className="top-right">
        <span className="model">{model}</span>
        {mode === "demo" && <DemoControls popOpen={popOpen} speed={speed} onTogglePop={onTogglePop} onSpeed={onSpeed} onReset={onReset} />}
        <a className="pill ghost sm" href={COPY.github.href} target="_blank" rel="noopener">
          <GitHubIcon />
          <span className="gh-label">{COPY.github.label}</span>
        </a>
      </div>
    </header>
  );
}

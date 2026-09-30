import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, type ReactNode } from "react";
import type { Workbench } from "./app/workbench";
import { Header } from "./components/Header";
import { ModalRoot } from "./components/dialogs/ModalRoot";
import { SessionsView } from "./components/sessions/SessionsView";
import { SettingsView } from "./components/settings/SettingsView";
import { VaultView } from "./components/vault/VaultView";
import { Bench } from "./components/workbench/Bench";
import { Conversation } from "./components/workbench/Conversation";
import { Idle } from "./components/workbench/Idle";
import { earlierData, Panel } from "./components/workbench/panels/Panel";
import { SUGGESTIONS } from "./demo/data";
import { usePointerGlow } from "./hooks/usePointerGlow";
import { COPY, fill } from "./lib/copy";
import { curSession, shownSession } from "./store/sessionOps";
import { StoresProvider, useRuns, useSession, useSettings, useStores, useUi, useVault, type Stores } from "./store/stores";
import type { Run, UiState, View } from "./store/types";
import { findTool } from "./store/vaultOps";

/** The app shell (lines 596–691): the header, the four views, then #modal-root. */
export function App({ stores, workbench }: { stores: Stores; workbench: Workbench }) {
  return (
    <StoresProvider stores={stores}>
      <Shell wb={workbench} />
    </StoresProvider>
  );
}

function Shell({ wb }: { wb: Workbench }) {
  usePointerGlow();
  const stores = useStores();
  // Boot (line 2296): S.booted, then showView(location.hash).
  useEffect(() => {
    stores.ui.set({ booted: true });
    wb.showView(window.location.hash.slice(1) || "workbench");
    const onHash = () => wb.showView(window.location.hash.slice(1));
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, [wb, stores]);
  return (
    <>
      <div className="app">
        <HeaderC wb={wb} />
        <div className="views">
          <ViewSection name="workbench" label={COPY.nav.workbench}>
            <div className="wb">
              <ConversationC wb={wb} />
              <BenchC wb={wb} />
            </div>
          </ViewSection>
          {/* Every view stays mounted (the reference only hides them), so per-instance state such as the vault detail's `swap` class survives. */}
          <ViewSection name="vault" label={COPY.nav.vault}>
            <VaultC wb={wb} />
          </ViewSection>
          <ViewSection name="sessions" label={COPY.nav.sessions}>
            <div className="sessions">
              <div className="sessions-in" id="sessions-in">
                <SessionsC wb={wb} />
              </div>
            </div>
          </ViewSection>
          <ViewSection name="settings" label={COPY.nav.settings}>
            <div className="settings">
              <div className="settings-in" id="settings-in">
                <SettingsC wb={wb} />
              </div>
            </div>
          </ViewSection>
        </div>
      </div>
      <div id="modal-root">
        <ModalC wb={wb} />
      </div>
    </>
  );
}

/** A `.view` section: hidden unless shown; a view change replays `enter` (showView, line 2083). */
function ViewSection({ name, label, children }: { name: View; label: string; children: ReactNode }) {
  const view = useUi((u) => u.view);
  const viewEnter = useUi((u) => u.viewEnter);
  const ref = useRef<HTMLElement>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || view !== name || viewEnter === 0) return;
    el.classList.remove("enter");
    void el.offsetWidth;
    el.classList.add("enter");
    // Only a view change (a viewEnter bump) replays it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewEnter]);
  return (
    <section className="view" id={`view-${name}`} aria-label={label} hidden={view !== name} ref={ref}>
      {children}
    </section>
  );
}

function HeaderC({ wb }: { wb: Workbench }) {
  const busy = useUi((u) => u.busy);
  const badge = useUi((u) => u.badge);
  const view = useUi((u) => u.view);
  const popOpen = useUi((u) => u.popOpen);
  const speed = useUi((u) => u.speed);
  const model = useSettings((s) => s.model);
  // Stable callbacks: DemoControls re-binds its document listeners when onTogglePop changes.
  const onTogglePop = useCallback((open?: boolean) => wb.togglePop(open), [wb]);
  const onSpeed = useCallback((s: number) => wb.setSpeed(s), [wb]);
  const onReset = useCallback(() => void wb.reset(), [wb]);
  return (
    <Header
      mode={wb.mode}
      busy={busy}
      badge={badge}
      view={view}
      model={model}
      popOpen={popOpen}
      speed={speed}
      onTogglePop={onTogglePop}
      onSpeed={onSpeed}
      onReset={onReset}
    />
  );
}

function ConversationC({ wb }: { wb: Workbench }) {
  const ss = useSession((s) => s);
  const busy = useUi((u) => u.busy);
  const draft = useUi((u) => u.draft);
  const live = useUi((u) => u.live);
  const titleAnimate = useUi((u) => u.titleAnimate);
  const titleSeq = useUi((u) => u.titleSeq);
  // markRunLinks() state, not S.viewing: the reference leaves the old run's link marked while a run goes.
  const viewingN = useUi((u) => u.markedRunN);
  const shown = shownSession(ss);
  const cur = curSession(ss);
  const readOnly = useMemo(() => (ss.viewId ? { name: shown.name, started: shown.started } : null), [ss.viewId, shown.name, shown.started]);
  const hint = ss.viewId ? fill(COPY.convo.hintPast, { name: cur.name }) : busy ? COPY.convo.hintBusy : COPY.convo.hintIdle;

  // setBusy(false) refocuses the composer on wide screens (line 1505).
  const askRef = useRef<HTMLTextAreaElement>(null);
  const wasBusy = useRef(busy);
  useEffect(() => {
    if (wasBusy.current && !busy && window.matchMedia("(min-width: 821px)").matches) askRef.current?.focus({ preventScroll: true });
    wasBusy.current = busy;
  }, [busy]);

  return (
    <Conversation
      title={shown.name}
      animateTitle={titleAnimate}
      titleSeq={titleSeq}
      readOnly={readOnly}
      messages={shown.messages}
      // An old session is never "empty": it shows the viewing note (openSession, line 2185).
      empty={!ss.viewId && shown.messages.length === 0}
      busy={busy}
      viewingN={viewingN}
      live={live}
      composer={{
        value: draft,
        busy,
        disabled: busy || !!ss.viewId,
        hint,
        onChange: (v) => wb.setDraft(v),
        onSubmit: () => void wb.submitDraft(),
        inputRef: askRef,
      }}
      onNew={() => void wb.newSession()}
      onBack={() => wb.backToNow()}
      onRun={(n) => wb.viewRun(n)}
      onSuggest={(i) => void wb.submit(SUGGESTIONS[i]!.q)}
    />
  );
}

function BenchC({ wb }: { wb: Workbench }) {
  const ss = useSession((s) => s);
  const byId = useRuns((s) => s.byId);
  const tools = useVault((v) => v.tools);
  const env = useSettings((s) => s.env);
  const liveSettings = useSettings((s) => s.live);
  const askExec = useSettings((s) => s.askExec);
  const busy = useUi((u) => u.busy);
  const benchKey = useUi((u) => u.benchKey);
  const currentRunId = useUi((u) => u.currentRunId);
  const viewingRunId = useUi((u) => u.viewingRunId);
  const run = viewingRunId ? byId[viewingRunId] : undefined;
  const runsOfShown = useMemo(() => shownSession(ss).runIds.map((id) => byId[id]).filter((r): r is Run => !!r), [ss, byId]);
  return (
    <main className="bench" id="bench" aria-label={COPY.bench.aria}>
      {!run ? (
        <Idle
          key={`idle-${benchKey}`}
          count={tools.length}
          weatherKeySet={!!env.OPENWEATHERMAP_API_KEY}
          askExec={askExec}
          keys={liveSettings ? { set: liveSettings.keys.filter((k) => k.set).length, total: liveSettings.keys.length } : undefined}
          onSuggest={(i) => void wb.submit(SUGGESTIONS[i]!.q)}
        />
      ) : (
        <Bench
          key={`${run.id}:${benchKey}`}
          run={run}
          live={busy && run.id === currentRunId && (run.status === "running" || run.status === "waiting")}
          panel={
            <Panel
              run={run}
              isCurrent={run.id === currentRunId}
              tool={findTool(tools, run.toolName)}
              earlier={earlierData(runsOfShown, run, !!ss.viewId)}
              onAsk={(q) => void wb.submit(q)}
              onOpenTool={(n) => wb.openTool(n)}
              onRun={(n) => wb.viewRun(n)}
            />
          }
          onTab={(t) => wb.selectTab(t)}
          onStop={() => void wb.stop()}
          onOpenTool={(n) => wb.openTool(n)}
        />
      )}
    </main>
  );
}

function VaultC({ wb }: { wb: Workbench }) {
  const tools = useVault((v) => v.tools);
  const sources = useVault((v) => v.sources);
  const filter = useUi((u) => u.filter);
  const query = useUi((u) => u.query);
  const selected = useUi((u) => u.selected);
  const stagger = useUi((u) => u.stagger);
  const vaultRender = useUi((u) => u.vaultRender);
  const confirmRemove = useUi((u) => u.confirmRemove);
  useEffect(() => {
    if (selected && sources[selected] === undefined) void wb.loadSource(selected);
  }, [wb, selected, sources]);
  const onFallbackSelect = useCallback((name: string | null) => wb.fallbackSelect(name), [wb]);
  return (
    <VaultView
      tools={tools}
      filter={filter}
      query={query}
      selected={selected}
      stagger={stagger}
      renderKey={vaultRender}
      confirmRemove={confirmRemove}
      source={selected ? (sources[selected] ?? null) : null}
      demo={wb.mode === "demo"}
      onQuery={(q) => wb.setQuery(q)}
      onFilter={(f: UiState["filter"]) => wb.setFilter(f)}
      onSelect={(n) => wb.selectTool(n)}
      onFallbackSelect={onFallbackSelect}
      onRead={(n) => void wb.readSource(n)}
      onUse={(n) => wb.useTool(n)}
      onRemove={(n) => wb.removeTool(n)}
      onOpenTool={(n) => wb.openTool(n)}
    />
  );
}

function SessionsC({ wb }: { wb: Workbench }) {
  const sessions = useSession((s) => s.sessions);
  const curId = useSession((s) => s.curId);
  const runsById = useRuns((s) => s.byId);
  return <SessionsView sessions={sessions} runsById={runsById} curId={curId} onOpen={(id) => wb.openSession(id)} />;
}

function SettingsC({ wb }: { wb: Workbench }) {
  const askExec = useSettings((s) => s.askExec);
  const env = useSettings((s) => s.env);
  const model = useSettings((s) => s.model);
  const live = useSettings((s) => s.live);
  return <SettingsView askExec={askExec} env={env} model={model} live={live} onToggleAsk={() => wb.toggleAskExec()} />;
}

function ModalC({ wb }: { wb: Workbench }) {
  const dialog = useUi((u) => u.dialog);
  return (
    <ModalRoot
      dialog={dialog}
      demo={wb.mode === "demo"}
      onApproval={(a) => wb.answerApproval(a)}
      onKey={(r) => wb.answerKey(r)}
      onClose={() => wb.closeReader()}
    />
  );
}

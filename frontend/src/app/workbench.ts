import { clearTestMarks } from "../components/workbench/panels/TestsPanel";
import { USE_PRESETS } from "../demo/data";
import { COPY, fill } from "../lib/copy";
import * as R from "../store/runOps";
import { initialStates, updateRun, type Stores } from "../store/stores";
import { curSession, openNewSession, rename, shownSession } from "../store/sessionOps";
import type { TabId, UiState, View } from "../store/types";
import { removeTool as dropTool } from "../store/vaultOps";
import type { Services } from "../services";
import { Player } from "../transport/player";

const VIEWS: View[] = ["workbench", "vault", "sessions", "settings"];

/** Every user action, with the reference's guards. Components call these; nothing else writes stores. */
export class Workbench {
  private players = new Map<string, Player>();

  constructor(
    private readonly stores: Stores,
    private readonly services: Services,
  ) {}

  get mode() {
    return this.services.mode;
  }

  private ui = (patch: Partial<UiState>) => this.stores.ui.set(patch);

  /** setTitle(name, true) (line 2168): the title decodes again, even when the name is unchanged. */
  private titleAnimated(): Partial<UiState> {
    return { titleAnimate: true, titleSeq: this.stores.ui.get().titleSeq + 1 };
  }

  /**
   * renderBench(run) (line 1086) for `id`: the bench is re-created. The reference redraws the log from
   * lines whose `fresh` flag it already dropped (line 1285), so the new LogPanel must not replay them.
   */
  private rebench(id: string | null, patch: Partial<UiState> = {}): void {
    if (id) updateRun(this.stores, id, R.clearFresh);
    this.ui({ ...patch, viewingRunId: id, benchKey: this.stores.ui.get().benchKey + 1 });
  }

  async submit(raw: string): Promise<void> {
    const text = raw.trim();
    const ui = this.stores.ui.get();
    if (!text || ui.busy || this.stores.session.get().viewId) return;
    this.ui({ busy: true });
    if (ui.view !== "workbench") window.location.hash = "workbench";
    const sid = this.stores.session.get().curId;
    const started = await this.services.transport.startRun(sid, text);
    const name = started.sessionName;
    if (name) {
      this.stores.session.update((s) => rename(s, sid, name));
      this.ui(this.titleAnimated());
    }
    const player = new Player(this.stores, {
      runId: started.runId,
      sessionId: sid,
      momentDwell: this.services.mode !== "demo",
      source: (tool) => this.services.data.toolSource(tool),
    });
    this.players.set(started.runId, player);
    this.ui({ benchKey: this.stores.ui.get().benchKey + 1 });
    this.services.transport.subscribe(started.runId, player.push);
  }

  /**
   * stopRun() (line 1485). The player is aborted first: the demo transport's stop waits for its flow,
   * which may be waiting on a player animation.
   */
  stop(): Promise<void> {
    const { currentRunId: id, busy } = this.stores.ui.get();
    if (!id || !busy) return Promise.resolve();
    this.players.get(id)?.abort();
    this.ui({ dialog: null });
    return this.services.transport.stop(id);
  }

  answerApproval(action: "yes" | "no" | "cancel"): void {
    const d = this.stores.ui.get().dialog;
    if (d?.kind !== "approval") return;
    this.ui({ dialog: null });
    if (action === "cancel") {
      void this.stop();
      return;
    }
    void this.services.transport.resume(d.runId, { decision: action === "yes" ? "approve" : "decline" });
  }

  answerKey(r: { action: "save"; value: string } | { action: "skip" } | { action: "cancel" }): void {
    const d = this.stores.ui.get().dialog;
    if (d?.kind !== "key") return;
    this.ui({ dialog: null });
    if (r.action === "cancel") {
      void this.stop();
      return;
    }
    void this.services.transport.resume(d.runId, r.action === "save" ? { decision: "save", value: r.value } : { decision: "skip" });
  }

  closeReader(): void {
    if (this.stores.ui.get().dialog?.kind === "reader") this.ui({ dialog: null });
  }

  selectTab(tab: TabId): void {
    const id = this.stores.ui.get().viewingRunId;
    if (id) updateRun(this.stores, id, (r) => R.setTab({ ...r, codeScroll: null }, tab));
  }

  viewRun(n: number): void {
    if (this.stores.ui.get().busy) return;
    const shown = shownSession(this.stores.session.get());
    const id = shown.runIds.find((rid) => this.stores.runs.get().byId[rid]?.n === n);
    if (!id) return;
    this.rebench(id);
    const bench = document.getElementById("bench");
    if (bench) bench.scrollTop = 0;
  }

  async newSession(): Promise<void> {
    if (this.stores.ui.get().busy) return;
    if (this.stores.session.get().viewId) this.backToNow();
    const rec = await this.services.data.newSession(this.stores.session.get().count + 1);
    this.stores.session.update((s) => openNewSession(s, rec));
    const ui = this.stores.ui.get();
    this.rebench(null, { currentRunId: null, ...(ui.booted ? this.titleAnimated() : { titleAnimate: false }) });
  }

  openSession(id: string): void {
    if (this.stores.ui.get().busy) return;
    const ss = this.stores.session.get();
    const sess = ss.sessions.find((x) => x.id === id);
    if (!sess) return;
    window.location.hash = "workbench";
    if (id === ss.curId) return this.backToNow();
    this.stores.session.set({ viewId: id });
    this.rebench(sess.runIds.at(-1) ?? null, this.titleAnimated());
    // msgs.scrollTop = 0 (line 2191), also when this session was already the one being read.
    const msgs = document.getElementById("msgs");
    if (msgs) msgs.scrollTop = 0;
  }

  backToNow(): void {
    const ss = this.stores.session.get();
    if (!ss.viewId) return;
    this.stores.session.set({ viewId: null });
    this.rebench(curSession(ss).runIds.at(-1) ?? null, this.titleAnimated());
  }

  showView(hash: string): void {
    const v = (VIEWS as string[]).includes(hash) ? (hash as View) : "workbench";
    const ui = this.stores.ui.get();
    const changed = ui.view !== v;
    const patch: Partial<UiState> = { view: v };
    if (changed) patch.viewEnter = ui.viewEnter + 1;
    if (v === "vault") Object.assign(patch, { badge: false, stagger: changed, vaultRender: ui.vaultRender + 1, confirmRemove: null });
    this.ui(patch);
  }

  setDraft(v: string): void {
    this.ui({ draft: v });
  }

  /** The composer's submit (line 2092): it always clears the box, then submits what was in it. */
  submitDraft(): Promise<void> {
    const v = this.stores.ui.get().draft;
    this.ui({ draft: "" });
    return this.submit(v);
  }

  private rerenderVault(stagger: boolean, patch: Partial<UiState> = {}): void {
    this.ui({ ...patch, stagger, vaultRender: this.stores.ui.get().vaultRender + 1, confirmRemove: null });
  }
  setQuery(q: string): void {
    this.rerenderVault(false, { query: q });
  }
  setFilter(f: UiState["filter"]): void {
    this.rerenderVault(true, { filter: f });
  }
  selectTool(name: string): void {
    this.rerenderVault(false, { selected: name });
    setTimeout(() => document.querySelector<HTMLElement>(`[data-tool-btn="${name}"]`)?.focus(), 0);
  }
  fallbackSelect(name: string | null): void {
    this.ui({ selected: name });
  }
  openTool(name: string): void {
    this.ui({ selected: name });
  }

  async loadSource(name: string): Promise<string[] | null> {
    const cached = this.stores.vault.get().sources[name];
    if (cached !== undefined) return cached;
    const lines = await this.services.data.toolSource(name);
    this.stores.vault.update((v) => ({ ...v, sources: { ...v.sources, [name]: lines } }));
    return lines;
  }
  async readSource(name: string): Promise<void> {
    const lines = await this.loadSource(name);
    if (lines) this.ui({ dialog: { kind: "reader", name, lines } });
  }

  useTool(name: string): void {
    window.location.hash = "workbench";
    this.ui({ draft: USE_PRESETS[name] ?? fill(COPY.vault.usePrefill, { name }) });
    setTimeout(() => {
      const ta = document.getElementById("ask") as HTMLTextAreaElement | null;
      if (!ta) return;
      ta.focus();
      ta.setSelectionRange(ta.value.length, ta.value.length);
    }, 30);
  }

  removeTool(name: string): void {
    if (this.stores.ui.get().confirmRemove !== name) {
      this.ui({ confirmRemove: name });
      return;
    }
    this.stores.vault.update((v) => ({ ...v, tools: dropTool(v.tools, name) }));
    void this.services.data.removeTool(name);
    this.rerenderVault(false, { selected: null });
  }

  toggleAskExec(): void {
    const on = !this.stores.settings.get().askExec;
    this.stores.settings.set({ askExec: on });
    void this.services.data.setAskBeforeExec(on);
  }

  togglePop(open?: boolean): void {
    this.ui({ popOpen: open ?? !this.stores.ui.get().popOpen });
  }
  setSpeed(speed: number): void {
    this.ui({ speed });
  }

  /** resetDemo() (line 2280). */
  async reset(): Promise<void> {
    this.services.demo?.reset(this.services.lastRunNumber);
    for (const p of this.players.values()) p.dispose();
    this.players.clear();
    // The run counter restarts, so run ids repeat: the tests panel's draw marks must go too.
    clearTestMarks();
    const data = this.services.data;
    const [tools, settings, past] = await Promise.all([data.vault(), data.settings(), data.sessions()]);
    const current = await data.newSession(1);
    const fresh = initialStates({ tools, settings, sessions: past.sessions, runs: past.runs, current, count: 1 });
    const ui = this.stores.ui.get();
    this.stores.runs.dispatch({ type: "reset", state: fresh.runs });
    this.stores.session.dispatch({ type: "reset", state: fresh.session });
    this.stores.vault.dispatch({ type: "reset", state: fresh.vault });
    this.stores.settings.dispatch({ type: "reset", state: fresh.settings });
    this.stores.ui.dispatch({
      type: "reset",
      state: {
        ...fresh.ui, view: ui.view, viewEnter: ui.viewEnter, speed: ui.speed, live: ui.live, booted: true,
        titleAnimate: true, titleSeq: ui.titleSeq + 1, benchKey: ui.benchKey + 1, vaultRender: ui.vaultRender + 1,
      },
    });
  }
}

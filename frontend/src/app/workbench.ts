import { effectiveSelected } from "../components/vault/VaultView";
import { clearTestMarks } from "../components/workbench/panels/TestsPanel";
import { LiveDataSource } from "../data/live";
import { USE_PRESETS } from "../demo/data";
import { COPY, fill } from "../lib/copy";
import * as R from "../store/runOps";
import { initialStates, updateRun, type Stores } from "../store/stores";
import { curSession, openNewSession, rename, shownSession } from "../store/sessionOps";
import type { TabId, UiState, View } from "../store/types";
import { removeTool as dropTool, vaultRows } from "../store/vaultOps";
import type { Services } from "../services";
import { ApiError } from "../transport/api";
import { Player } from "../transport/player";
import type { RunEvent } from "../transport/types";

const VIEWS: View[] = ["workbench", "vault", "sessions", "settings"];
/** Re-attach: a waiting run's dialog opens from GET /api/runs/{id}.pending once its backlog has been quiet this long (ruling 3). */
const BACKLOG_QUIET_MS = 150;
/** Re-attach: a failed GET /api/runs/{id} is retried after this, doubling up to the cap. */
const PENDING_RETRY_MS = 1000;
const PENDING_RETRY_CAP_MS = 30_000;

type Pending = NonNullable<Awaited<ReturnType<LiveDataSource["getRun"]>>["pending"]>;
/** The dialog for a paused run's pending interrupt. */
const pendingDialog = (runId: string, p: Pending): UiState["dialog"] =>
  p.kind === "confirm_exec"
    ? { kind: "approval", runId, tool: p.payload.tool, code: p.payload.preview }
    : { kind: "key", runId, toolName: p.payload.tool_name, envVar: p.payload.env_var, service: p.payload.service };
const logError = (err: unknown) => console.error(err);

/** Every user action, with the reference's guards. Components call these; nothing else writes stores. */
export class Workbench {
  private players = new Map<string, Player>();
  /** Live: each followed run's stream, closed and dropped with its player once the run has finished. */
  private streams = new Map<string, () => void>();
  /** Live: runs whose full state is in the store (replayed, re-attached or played live), not just a stub. */
  private hydrated = new Set<string>();
  private hydrating = new Map<string, Promise<void>>();
  private viewSeq = 0;
  /** Bench navigation (boot, viewRun, openSession, backToNow, runs): the last one wins over a slower replay. */
  private navSeq = 0;

  constructor(
    private readonly stores: Stores,
    private readonly services: Services,
  ) {}

  get mode() {
    return this.services.mode;
  }

  private get live(): LiveDataSource | null {
    return this.services.mode === "live" && this.services.data instanceof LiveDataSource ? this.services.data : null;
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
    this.navSeq++;
    this.ui({ busy: true });
    if (ui.view !== "workbench") window.location.hash = "workbench";
    const sid = this.stores.session.get().curId;
    try {
      const started = await this.services.transport.startRun(sid, text);
      const name = started.sessionName;
      if (name) {
        this.stores.session.update((s) => rename(s, sid, name));
        this.ui(this.titleAnimated());
      }
      const player = new Player(this.stores, {
        runId: started.runId,
        sessionId: sid,
        // DemoTransport performs the moment dwells itself (ruling 4); any other transport needs the player's.
        momentDwell: this.services.demo === null,
        source: (tool) => this.services.data.toolSource(tool),
      });
      this.players.set(started.runId, player);
      this.hydrated.add(started.runId);
      this.ui({ benchKey: this.stores.ui.get().benchKey + 1 });
      const off = this.services.transport.subscribe(started.runId, this.live ? this.liveSink(started.runId, player) : player.push);
      if (this.live) this.streams.set(started.runId, off);
    } catch (e) {
      // submit()'s catch and finally (lines 1476-1479): the run couldn't start, so the app isn't busy.
      this.ui({ busy: false });
      // Ruling 10: a run is already going. Follow it when it's in this session; there's no copy for the rest.
      if (e instanceof ApiError && e.code === "run_active") {
        if (e.sessionId === sid && e.runId) this.reattach(e.runId);
        return;
      }
      console.error(e);
    }
  }

  /** Live only: show the current session's last run, or re-attach to it if it is still going (spec 04 §6). */
  async boot(): Promise<void> {
    if (!this.live) return;
    const lastId = curSession(this.stores.session.get()).runIds.at(-1);
    if (!lastId) return;
    const last = this.stores.runs.get().byId[lastId];
    if (last && (last.status === "running" || last.status === "waiting")) return this.reattach(lastId);
    const seq = ++this.navSeq;
    await this.hydrate(lastId);
    if (seq !== this.navSeq) return;
    this.rebench(lastId);
    this.markRunLinks();
  }

  /** Live: a finished run that is still a stub is replayed from its event log into the same run id (ruling 4). */
  private hydrate(id: string): Promise<void> {
    const live = this.live;
    if (!live || this.hydrated.has(id)) return Promise.resolve();
    let p = this.hydrating.get(id);
    if (!p) {
      p = this.replay(live, id).finally(() => this.hydrating.delete(id));
      this.hydrating.set(id, p);
    }
    return p;
  }

  private async replay(live: LiveDataSource, id: string): Promise<void> {
    const stub = this.stores.runs.get().byId[id];
    if (!stub) return;
    const active = (st: string) => st === "running" || st === "waiting";
    try {
      // A stub listed while its run was going may have finished since (e.g. a run from another tab).
      if (active(stub.status) && (this.players.has(id) || active((await live.getRun(id)).status))) return;
      const events = await live.runEvents(id);
      const player = new Player(this.stores, { runId: id, sessionId: stub.sessionId, momentDwell: false, replay: true, source: (t) => live.toolSource(t) });
      for (const e of events) await player.push(e);
      this.hydrated.add(id);
    } catch (err) {
      console.error(err);
    }
  }

  /**
   * Live: follow a running or waiting run from seq 0 (ruling 3). Its backlog applies at once; later
   * events are paced. The player opens no dialog for a caught-up interrupt, so whenever the stream goes
   * quiet while the run is paused on one that has no dialog yet, the dialog opens from
   * GET /api/runs/{id}.pending: once per interrupt, never after it was resolved, and not after Stop.
   */
  private reattach(runId: string): void {
    const live = this.live;
    if (!live || this.players.has(runId)) return;
    const sid = this.stores.session.get().curId;
    const cutoff = new Date().toISOString();
    const cut = Date.parse(cutoff);
    const player = new Player(this.stores, { runId, sessionId: sid, momentDwell: true, source: (t) => live.toolSource(t), catchUpUntil: cutoff });
    this.players.set(runId, player);
    this.hydrated.add(runId);
    this.navSeq++;
    this.ui({ busy: true, currentRunId: runId, viewingRunId: runId, benchKey: this.stores.ui.get().benchKey + 1 });
    /* The seq of the unresolved interrupt, and of the last interrupt whose dialog was shown. */
    let open: number | null = null;
    let shown: number | null = null;
    let quiet: ReturnType<typeof setTimeout> | null = null;
    let retry = PENDING_RETRY_MS;
    // The source reader is only a view: the paused run's dialog replaces it.
    const blocking = () => {
      const d = this.stores.ui.get().dialog;
      return !!d && d.kind !== "reader";
    };
    const unanswered = (want: number) =>
      open === want && shown !== want && !player.stopped && !blocking() && this.stores.runs.get().byId[runId]?.status === "waiting";
    const openPending = async () => {
      quiet = null;
      const want = open;
      if (want === null || !unanswered(want)) return;
      let info: Awaited<ReturnType<LiveDataSource["getRun"]>>;
      try {
        info = await live.getRun(runId);
      } catch (err) {
        console.error(err);
        // Tried again with backoff while the interrupt is still unanswered; a new stream event re-arms it too.
        if (open === want && quiet === null) {
          quiet = setTimeout(() => void openPending(), retry);
          retry = Math.min(retry * 2, PENDING_RETRY_CAP_MS);
        }
        return;
      }
      retry = PENDING_RETRY_MS;
      const p = info.pending;
      if (info.status !== "waiting" || !p || !unanswered(want)) return;
      shown = want;
      this.ui({ dialog: pendingDialog(runId, p) });
    };
    const sink = this.liveSink(runId, player);
    const off = this.services.transport.subscribe(runId, async (e) => {
      // Tracked on arrival, in stream order. A later interrupt's dialog is the player's own.
      if (e.type === "interrupt") {
        open = e.seq;
        if (!(Date.parse(e.ts) <= cut)) shown = e.seq;
      } else if (e.type === "interrupt.resolved" || e.type === "run.finished") open = null;
      await sink(e);
      if (quiet) clearTimeout(quiet);
      quiet = open === null || shown === open ? null : setTimeout(() => void openPending(), BACKLOG_QUIET_MS);
    });
    this.streams.set(runId, off);
  }

  /**
   * Wraps a live player's sink: after run.finished the vault store is reloaded (the API owns counts and
   * freshness), and the run's stream and player are let go.
   */
  private liveSink(runId: string, player: Player): (e: RunEvent) => Promise<void> {
    return async (e) => {
      await player.push(e);
      if (e.type !== "run.finished") return;
      this.streams.get(runId)?.();
      this.streams.delete(runId);
      if (this.players.get(runId) === player) this.players.delete(runId);
      await this.refreshVault().catch(logError);
    };
  }

  /** Live: after a failed /resume the run is still paused, so its dialog comes back from GET /api/runs/{id}.pending. */
  private async reopenPending(runId: string): Promise<void> {
    const live = this.live;
    if (!live) return;
    try {
      const info = await live.getRun(runId);
      const ui = this.stores.ui.get();
      if (info.status !== "waiting" || !info.pending || ui.dialog || ui.currentRunId !== runId || this.players.get(runId)?.stopped) return;
      this.ui({ dialog: pendingDialog(runId, info.pending) });
    } catch (err) {
      console.error(err);
    }
  }

  private resume(runId: string, decision: Parameters<Services["transport"]["resume"]>[1]): void {
    this.services.transport.resume(runId, decision).catch((err: unknown) => {
      console.error(err);
      void this.reopenPending(runId);
    });
  }

  /** Live: GET /api/settings. */
  private async refreshSettings(): Promise<void> {
    const live = this.live;
    if (live) this.stores.settings.set(await live.settings());
  }

  /** Live: GET /api/vault. Sources are kept, except those of tools that are gone. */
  private async refreshVault(): Promise<void> {
    const live = this.live;
    if (!live) return;
    const tools = await live.vault();
    const names = new Set(tools.map((t) => t.name));
    this.stores.vault.update((v) => ({ ...v, tools, sources: Object.fromEntries(Object.entries(v.sources).filter(([k]) => names.has(k))) }));
  }

  /** Live: sessions the store doesn't have yet (e.g. from another tab) join as past sessions with stub runs. */
  private async refreshSessions(): Promise<void> {
    const live = this.live;
    if (!live) return;
    const list = await live.listSessions();
    const known = new Set(this.stores.session.get().sessions.map((x) => x.id));
    const fresh = list.filter((x) => !known.has(x.id));
    if (!fresh.length) return;
    const loaded = await live.loadSessions(fresh);
    const runs = loaded.flatMap((l) => l.runs);
    this.stores.runs.update((st) => ({ byId: { ...st.byId, ...Object.fromEntries(runs.map((r) => [r.id, r])) } }));
    this.stores.session.update((st) => {
      const ids = new Set(st.sessions.map((x) => x.id));
      const add = loaded.map((l) => l.rec).filter((r) => !ids.has(r.id));
      return { ...st, sessions: [...add.map((r) => ({ ...r, live: false })), ...st.sessions] };
    });
  }

  /** Live: the store a view shows is refreshed from the API before the view renders. */
  private async refreshView(v: View): Promise<void> {
    if (v === "vault") {
      // During a run the player keeps the counts (it adds this run's use or failure when it shows it), and
      // the refresh after run.finished reconciles them. A refresh now would count the run's call twice.
      if (!this.stores.ui.get().busy) await this.refreshVault();
      const { filter, query, selected } = this.stores.ui.get();
      const tools = this.stores.vault.get().tools;
      const first = effectiveSelected(tools, vaultRows(tools, filter, query), selected);
      if (first && first !== selected) await this.loadSource(first);
    } else if (v === "sessions") await this.refreshSessions();
    else if (v === "settings") await this.refreshSettings();
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
    const stopping = this.services.transport.stop(id);
    // Ruling 10: a failed /stop is logged; there's no copy for it. (The demo's rejects only on Reset.)
    return this.live ? stopping.catch(logError) : stopping;
  }

  answerApproval(action: "yes" | "no" | "cancel"): void {
    const d = this.stores.ui.get().dialog;
    if (d?.kind !== "approval") return;
    this.ui({ dialog: null });
    if (action === "cancel") {
      void this.stop();
      return;
    }
    this.resume(d.runId, { decision: action === "yes" ? "approve" : "decline" });
  }

  answerKey(r: { action: "save"; value: string } | { action: "skip" } | { action: "cancel" }): void {
    const d = this.stores.ui.get().dialog;
    if (d?.kind !== "key") return;
    this.ui({ dialog: null });
    if (r.action === "cancel") {
      void this.stop();
      return;
    }
    this.resume(d.runId, r.action === "save" ? { decision: "save", value: r.value } : { decision: "skip" });
  }

  closeReader(): void {
    if (this.stores.ui.get().dialog?.kind === "reader") this.ui({ dialog: null });
  }

  selectTab(tab: TabId): void {
    const id = this.stores.ui.get().viewingRunId;
    if (id) updateRun(this.stores, id, (r) => R.setTab({ ...r, codeScroll: null }, tab));
  }

  viewRun(n: number): Promise<void> | void {
    if (this.stores.ui.get().busy) return;
    const shown = shownSession(this.stores.session.get());
    const id = shown.runIds.find((rid) => this.stores.runs.get().byId[rid]?.n === n);
    if (!id) return;
    const seq = ++this.navSeq;
    return this.thenShow(this.live ? () => this.hydrate(id) : null, () => {
      if (seq !== this.navSeq || this.stores.ui.get().busy) return;
      this.rebench(id);
      const bench = document.getElementById("bench");
      if (bench) bench.scrollTop = 0;
      this.markRunLinks();
    });
  }

  /**
   * Runs `show` after the live-only `prep` (a replay or an API refresh). With no `prep` it runs at once and
   * nothing is returned, so demo actions stay synchronous, as part A's callers (and act()) expect.
   */
  private thenShow(prep: (() => Promise<void>) | null, show: () => void): Promise<void> | void {
    if (!prep) return show();
    return prep().then(show);
  }

  async newSession(): Promise<void> {
    if (this.stores.ui.get().busy) return;
    if (this.stores.session.get().viewId) await this.backToNow();
    const live = this.live;
    let rec: { id: string; name: string; started: string };
    try {
      rec = live ? await live.newSession() : await this.services.data.newSession(this.stores.session.get().count + 1);
    } catch (err) {
      // Ruling 10: API errors are logged; there is no copy for them.
      console.error(err);
      return;
    }
    this.navSeq++;
    if (live) {
      // "New this session" follows the new session.
      live.setCurrentStarted(rec.started);
      // Ruling 7: the server reuses the newest empty session, so the current one may come back.
      if (rec.id === this.stores.session.get().curId) {
        this.ui(this.titleAnimated());
        return;
      }
    }
    this.stores.session.update((s) => openNewSession(s, rec));
    const ui = this.stores.ui.get();
    this.rebench(null, { currentRunId: null, ...(ui.booted ? this.titleAnimated() : { titleAnimate: false }) });
  }

  openSession(id: string): Promise<void> | void {
    if (this.stores.ui.get().busy) return;
    const ss = this.stores.session.get();
    const sess = ss.sessions.find((x) => x.id === id);
    if (!sess) return;
    window.location.hash = "workbench";
    if (id === ss.curId) return this.backToNow();
    const target = sess.runIds.at(-1) ?? null;
    const seq = ++this.navSeq;
    return this.thenShow(this.live && target ? () => this.hydrate(target) : null, () => {
      if (seq !== this.navSeq || this.stores.ui.get().busy) return;
      this.stores.session.set({ viewId: id });
      this.rebench(target, this.titleAnimated());
      this.markRunLinks();
      // msgs.scrollTop = 0 (line 2191), also when this session was already the one being read.
      const msgs = document.getElementById("msgs");
      if (msgs) msgs.scrollTop = 0;
    });
  }

  backToNow(): Promise<void> | void {
    const ss = this.stores.session.get();
    if (!ss.viewId) return;
    const target = curSession(ss).runIds.at(-1) ?? null;
    const seq = ++this.navSeq;
    return this.thenShow(this.live && target ? () => this.hydrate(target) : null, () => {
      if (seq !== this.navSeq) return;
      this.stores.session.set({ viewId: null });
      this.rebench(target, this.titleAnimated());
      this.markRunLinks();
    });
  }

  /** markRunLinks() (line 2232): marks the link of the run on the bench, if any. */
  private markRunLinks(): void {
    const id = this.stores.ui.get().viewingRunId;
    this.ui({ markedRunN: id ? (this.stores.runs.get().byId[id]?.n ?? null) : null });
  }

  showView(hash: string): Promise<void> | void {
    const v = (VIEWS as string[]).includes(hash) ? (hash as View) : "workbench";
    // Live: entering Vault, Sessions or Settings refreshes its store first. A later showView wins a race.
    const seq = ++this.viewSeq;
    const live = this.live;
    const prep =
      live && v !== "workbench" && this.stores.ui.get().view !== v
        ? () => this.refreshView(v).catch((err: unknown) => console.error(err))
        : null;
    return this.thenShow(prep, () => {
      if (seq !== this.viewSeq) return;
      const ui = this.stores.ui.get();
      const changed = ui.view !== v;
      const patch: Partial<UiState> = { view: v };
      if (changed) patch.viewEnter = ui.viewEnter + 1;
      if (v === "vault") Object.assign(patch, { badge: false, stagger: changed, vaultRender: ui.vaultRender + 1, confirmRemove: null });
      this.ui(patch);
    });
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
  selectTool(name: string): Promise<void> | void {
    // Live: the source is in place before the detail cross-fades, so it renders once.
    const prep = this.live ? () => this.loadSource(name).then(() => undefined, (err: unknown) => console.error(err)) : null;
    return this.thenShow(prep, () => {
      this.rerenderVault(false, { selected: name });
      const sel = globalThis.CSS?.escape?.(name) ?? name;
      setTimeout(() => document.querySelector<HTMLElement>(`[data-tool-btn="${sel}"]`)?.focus(), 0);
    });
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
    // Optimistic: if the server says no, the vault comes back from the API.
    this.services.data.removeTool(name).catch((err: unknown) => {
      console.error(err);
      void this.refreshVault().then(() => this.rerenderVault(false), logError);
    });
    this.rerenderVault(false, { selected: null });
  }

  toggleAskExec(): void {
    const on = !this.stores.settings.get().askExec;
    this.stores.settings.set({ askExec: on });
    this.services.data.setAskBeforeExec(on).catch((err: unknown) => {
      console.error(err);
      void this.refreshSettings().catch(logError);
    });
  }

  togglePop(open?: boolean): void {
    this.ui({ popOpen: open ?? !this.stores.ui.get().popOpen });
  }
  setSpeed(speed: number): void {
    this.ui({ speed });
  }

  /** resetDemo() (line 2280). */
  async reset(): Promise<void> {
    // The Reset button is a Demo control (spec 04 §8.1): live mode never renders it.
    if (this.services.mode !== "demo") return;
    // if (S.busy) stopRun(). In demo mode the stop's events are dropped by the reset below; in live mode
    // (part B) this is what tells the server to stop the run before the stores are reloaded.
    // The demo stop then ends early (its run is silenced), so its rejection is expected and dropped.
    if (this.stores.ui.get().busy) this.stop().catch(() => {});
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
        // resetDemo() leaves #ask alone (it only clears #v-search), so the composer keeps its text.
        ...fresh.ui, view: ui.view, viewEnter: ui.viewEnter, speed: ui.speed, live: ui.live, draft: ui.draft, booted: true,
        titleAnimate: true, titleSeq: ui.titleSeq + 1, benchKey: ui.benchKey + 1, vaultRender: ui.vaultRender + 1,
      },
    });
  }
}

import { initStrip, nextKey, STRIPS } from "../store/runOps";
import type { CallArg, LogLine, Message, NodeState, Run, SessionRec, VaultTool } from "../store/types";
import type { StepKey } from "../transport/types";

interface Seed {
  forge?: boolean;
  tool: string;
  query: string;
  args: CallArg[];
  result: string;
  type: string;
  answer: string;
  label?: string;
  log?: [string, string, string?][];
}

function staticRun(n: number, sessionId: string, o: Seed, tools: VaultTool[]): Run {
  const t = tools.find((x) => x.name === o.tool) ?? { args: "", ret: "" };
  let run: Run = {
    id: `run-${n}`, sessionId, n, query: o.query, tab: "call", status: "done", log: [], nodes: {}, links: {}, tabs: [], strip: "forge",
    seeded: true, answer: o.answer, toolUsed: o.tool, forged: !!o.forge,
  };
  run = initStrip(run, o.forge ? "forge" : "vault");
  const st: Partial<Record<StepKey, NodeState>> = o.forge
    ? { planner: "done", forger: "forge", tester: "forge", human: "skip", learn: "done", executor: "done", answer: "answer" }
    : { planner: "done", vault: "done", skip: "skip", executor: "done", answer: "answer" };
  const nodes = { ...run.nodes };
  for (const [k, state] of Object.entries(st) as [StepKey, NodeState][]) {
    const node = nodes[k];
    if (node) nodes[k] = { ...node, state };
  }
  const keys = STRIPS[run.strip].map((x) => x[0]);
  const links: Record<string, boolean> = {};
  for (let i = 0; i < keys.length - 1; i++) links[`${keys[i]}-${keys[i + 1]}`] = true;
  const L = (label: string, text: string, tone?: string): LogLine => ({ label, text, tone, kind: "ln", key: nextKey() });
  const lines = o.log
    ? o.log.map((x) => L(...x))
    : o.forge
      ? [L("plan", "1 sub-task, needs a new tool"), L("vault", "no match"), L("forge", `${o.tool}()`, "g"), L("test", "passed", "g"), L("learn", "saved to the vault"), L("execute", "done", "w")]
      : [L("plan", "1 sub-task, in the vault"), L("vault", o.tool), L("execute", "done", "w")];
  const logStatus = o.forge ? "1 tool forged" : "0 tools forged";
  return {
    ...run, nodes, links,
    label: o.label || (o.forge ? "Sub-task 1 of 1, forged" : "Sub-task 1 of 1, found in the vault"),
    sig: { name: o.tool, args: t.args, ret: t.ret },
    caption: o.forge ? "Forged, tested and saved to the vault in this run." : "Done from the vault. The forge sub-graph never ran.",
    tabs: [{ id: "call", label: "Call" }],
    tab: "call",
    call: { args: o.args, result: o.result, resultType: o.type },
    log: [{ kind: "cmd", text: o.query, key: nextKey() }, ...lines],
    logStatus, logStatusGold: !!o.forge, logTone: o.forge ? "" : "warm",
    summary: logStatus, summaryGold: !!o.forge,
  };
}

/** sessionHtml() (line 2229) as messages: no word wrapping, one chip, a run link. */
function transcript(runs: Run[]): Message[] {
  return runs.flatMap((r): Message[] => [
    { kind: "you", key: `you-${r.n}`, text: r.query, past: false },
    {
      kind: "talos", key: `talos-${r.n}`, runN: r.n, status: null, html: r.answer ?? "", wrap: false, wordsOn: 0, note: null,
      chips: [{ kind: r.forged ? "forged" : "reused", text: `${r.forged ? "Forged" : "Reused"} ${r.toolUsed}${r.forged ? "" : " from the vault"}` }],
      suggest: false, stopNote: null, runLink: true, past: false,
    },
  ]);
}

export function seedSessions(tools: VaultTool[]): { sessions: SessionRec[]; runs: Run[]; lastRunNumber: number } {
  const b64 = "VGFsb3MgZm9yZ2VzIHRvb2xzIGF0IHJ1bnRpbWU=";
  let n = 0;
  const mk = (sid: string, o: Seed) => staticRun(++n, sid, o, tools);
  const seeds: { id: string; name: string; started: string; runs: Run[] }[] = [
    { id: "seed-fib", name: "Fibonacci tools", started: "2026-09-28T14:20", runs: [
      mk("seed-fib", { forge: true, tool: "nth_fibonacci", query: "Build me a tool that returns the Nth Fibonacci number. Then use it to get the 20th Fibonacci number.", args: [["n", "20"]], result: "6765", type: "int", answer: "The 20th Fibonacci number is 6765." }),
      mk("seed-fib", { tool: "nth_fibonacci", query: "What is the 30th Fibonacci number?", args: [["n", "30"]], result: "832040", type: "int", answer: "It's 832040." }),
    ] },
    { id: "seed-lev", name: "Edit distance", started: "2026-09-28T14:23", runs: [
      mk("seed-lev", { forge: true, tool: "levenshtein_distance", query: 'Forge a tool that computes the Levenshtein edit distance between two strings. What\'s the distance between "kitten" and "sitting"?', args: [["s1", '"kitten"'], ["s2", '"sitting"']], result: "3", type: "int", answer: 'The edit distance between "kitten" and "sitting" is 3.' }),
      mk("seed-lev", { tool: "levenshtein_distance", query: 'How similar are the words "algorithm" and "altruistic"? Use edit distance.', args: [["s1", '"algorithm"'], ["s2", '"altruistic"']], result: "6", type: "int", answer: "They're 6 edits apart, so not very similar." }),
    ] },
    { id: "seed-b64", name: "Base64 round trip", started: "2026-09-28T14:29", runs: [
      mk("seed-b64", { forge: true, tool: "base64_codec", label: "Sub-task 2 of 2, decode", query: 'Build a tool that base64-encodes and decodes strings. Encode "Talos forges tools at runtime" and then decode the result to verify.', args: [["text", `"${b64}"`], ["mode", '"decode"']], result: "'Talos forges tools at runtime'", type: "str",
        answer: `Encoded, it's <span class="mono">${b64}</span>. Decoding that gives back "Talos forges tools at runtime", so the round trip works.`,
        log: [["plan", "2 sub-tasks, 1 needs a new tool"], ["vault", "no match"], ["forge", "base64_codec()", "g"], ["test", "passed", "g"], ["learn", "saved to the vault"], ["execute", "encode, done", "w"], ["vault", "base64_codec"], ["execute", "decode, done", "w"]] }),
    ] },
  ];
  return {
    sessions: seeds.map((x) => ({ id: x.id, name: x.name, started: x.started, live: false, runIds: x.runs.map((r) => r.id), messages: transcript(x.runs) })),
    runs: seeds.flatMap((x) => x.runs),
    lastRunNumber: n,
  };
}

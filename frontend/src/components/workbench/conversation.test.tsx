import { act, render } from "@testing-library/react";
import { setReducedMotion } from "../../test/media";
import { Conversation, type ConversationProps } from "./Conversation";
import { expectParity, fixtureCase } from "../../test/parity";
import { ssr } from "../../test/ssr";
import { seedSessions } from "../../demo/seeds";
import { freshVault } from "../../store/vaultOps";
import { VAULT_ROWS } from "../../demo/data";
import type { TalosMessage } from "../../store/types";
import { Message } from "./Message";

const noop = () => {};
const talos = (p: Partial<TalosMessage>): TalosMessage => ({
  kind: "talos", key: "t", runN: 6, status: "Working on it", html: null, wrap: true, wordsOn: 0, note: null, chips: [],
  suggest: false, stopNote: null, runLink: false, past: false, ...p,
});

test("a You message escapes its text (addYou)", () => {
  const c = fixtureCase("convo/you");
  expectParity(ssr(<Message msg={{ kind: "you", key: "y", text: c.state.text as string, past: false }} showPast viewingN={null} onRun={noop} onSuggest={noop} />), c.html!);
});

test("a Talos message thinking (addTalos + status)", () => {
  const c = fixtureCase("convo/talos-thinking");
  expectParity(ssr(<Message msg={talos({ status: c.state.status as string })} showPast viewingN={null} onRun={noop} onSuggest={noop} />), c.html!);
});

test("a seeded transcript (sessionHtml)", () => {
  const c = fixtureCase("convo/seeded-fib");
  const fib = seedSessions(freshVault(VAULT_ROWS)).sessions[0]!;
  const html = fib.messages.map((m) => ssr(<Message msg={m} showPast viewingN={null} onRun={noop} onSuggest={noop} />)).join("");
  // sessionHtml() has no aria-current on its run links until markRunLinks() runs; the app always marks them.
  expectParity(html.replace(/ aria-current="false"/g, ""), c.html!);
});

test("answer words fade in on the same elements", () => {
  const html = 'It decrypts to <span class="mono">TALOS AGENT</span>.';
  const { container, rerender } = render(<Message msg={talos({ status: null, html, wordsOn: 0 })} showPast viewingN={null} onRun={noop} onSuggest={noop} />);
  const first = container.querySelector(".wd")!;
  expect(first.className).toBe("wd");
  rerender(<Message msg={talos({ status: null, html, wordsOn: 2 })} showPast viewingN={null} onRun={noop} onSuggest={noop} />);
  expect(container.querySelector(".wd")).toBe(first);
  expect([...container.querySelectorAll(".wd")].map((w) => w.className)).toEqual(["wd on", "wd on", "wd", "wd", "wd", "wd"]);
});

const you = (n: number) => ({ kind: "you" as const, key: `y${n}`, text: `q${n}`, past: false });
const convo = (p: Partial<ConversationProps> = {}): ConversationProps => ({
  title: "Session 1", animateTitle: false, readOnly: null, messages: [you(1)], empty: false, busy: false, viewingN: null, live: "",
  composer: { value: "", disabled: false, hint: "", busy: false, onChange: noop, onSubmit: noop },
  onNew: noop, onBack: noop, onRun: noop, onSuggest: noop, ...p,
});
/** jsdom has no layout: give #msgs a height and a real scrollTop. */
function fakeScroll(el: HTMLElement): { top: () => number; set: (v: number) => void } {
  let top = 0;
  Object.defineProperty(el, "scrollHeight", { configurable: true, get: () => 500 });
  Object.defineProperty(el, "scrollTop", { configurable: true, get: () => top, set: (v: number) => void (top = v) });
  return { top: () => top, set: (v) => void (top = v) };
}

test("the conversation scrolls only when messages are added, not while typing or marking run links", () => {
  const { container, rerender } = render(<Conversation {...convo()} />);
  const s = fakeScroll(container.querySelector<HTMLElement>("#msgs")!);
  s.set(100); // the reader scrolled up
  rerender(<Conversation {...convo({ composer: { ...convo().composer, value: "typing" } })} />);
  rerender(<Conversation {...convo({ viewingN: 3 })} />);
  rerender(<Conversation {...convo({ busy: true, live: "Talos: hi" })} />);
  expect(s.top()).toBe(100);
  rerender(<Conversation {...convo({ messages: [you(1), you(2)] })} />);
  expect(s.top()).toBe(500);
  s.set(100);
  const t = talos({ key: "t2", status: "Planning" });
  rerender(<Conversation {...convo({ messages: [you(1), t] })} />);
  expect(s.top()).toBe(500);
  s.set(100);
  rerender(<Conversation {...convo({ messages: [you(1), { ...t, status: "Forging" }] })} />);
  expect(s.top()).toBe(500);
});

test("an old session opens at the top and Back to now returns to the bottom", () => {
  const { container, rerender } = render(<Conversation {...convo()} />);
  const s = fakeScroll(container.querySelector<HTMLElement>("#msgs")!);
  s.set(250);
  rerender(<Conversation {...convo({ readOnly: { name: "Fibonacci tools", started: "2026-09-28T14:20" }, messages: [you(9)] })} />);
  expect(s.top()).toBe(0);
  s.set(40);
  rerender(<Conversation {...convo({ readOnly: { name: "Fibonacci tools", started: "2026-09-28T14:20" }, messages: [you(9)], viewingN: 2 })} />);
  expect(s.top()).toBe(40);
  rerender(<Conversation {...convo()} />);
  expect(s.top()).toBe(500);
});

test("a title change without animation shows the new title, even mid-decode", () => {
  setReducedMotion(false);
  vi.useFakeTimers({ toFake: ["requestAnimationFrame", "cancelAnimationFrame", "performance"] });
  const { container, rerender } = render(<Conversation {...convo({ title: "Session 1" })} />);
  rerender(<Conversation {...convo({ title: "Caesar cipher", animateTitle: true })} />);
  act(() => void vi.advanceTimersByTime(100));
  rerender(<Conversation {...convo({ title: "Session 2", animateTitle: false })} />);
  expect(container.querySelector("#session-title")!.textContent).toBe("Session 2");
  act(() => void vi.advanceTimersByTime(1000));
  expect(container.querySelector("#session-title")!.textContent).toBe("Session 2");
  vi.useRealTimers();
});

test("a titleSeq bump decodes the title again even when the name is unchanged (openSession on the same session)", () => {
  setReducedMotion(false);
  vi.useFakeTimers({ toFake: ["requestAnimationFrame", "cancelAnimationFrame", "performance"] });
  const { container, rerender } = render(<Conversation {...convo({ title: "Fibonacci tools", animateTitle: true, titleSeq: 1 })} />);
  const el = container.querySelector("#session-title")!;
  rerender(<Conversation {...convo({ title: "Fibonacci tools", animateTitle: true, titleSeq: 1 })} />);
  act(() => void vi.advanceTimersByTime(100));
  expect(el.textContent).toBe("Fibonacci tools");
  rerender(<Conversation {...convo({ title: "Fibonacci tools", animateTitle: true, titleSeq: 2 })} />);
  act(() => void vi.advanceTimersByTime(100));
  expect(el.textContent).not.toBe("Fibonacci tools");
  act(() => void vi.advanceTimersByTime(1000));
  expect(el.textContent).toBe("Fibonacci tools");
  vi.useRealTimers();
});

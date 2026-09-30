import { render } from "@testing-library/react";
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

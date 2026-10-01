import { fireEvent, render, screen } from "@testing-library/react";
import { SOURCES } from "../../demo/data";
import { expectParity, fixtureCase, snap } from "../../test/parity";
import { innerOf, ssr } from "../../test/ssr";
import type { VaultTool } from "../../store/types";
import { VaultView, type VaultViewProps } from "./VaultView";

const noop = () => {};
const view = (s: Record<string, unknown>, extra: Partial<VaultViewProps> = {}) => (
  <VaultView
    tools={s.tools as VaultTool[]}
    filter={(s.filter as VaultViewProps["filter"]) ?? "all"}
    query={(s.query as string) ?? ""}
    selected={(s.selected as string | null) ?? null}
    stagger={!!s.stagger}
    renderKey={0}
    demo
    confirmRemove={null}
    source={(s.source as string[] | undefined) ?? null}
    onQuery={noop} onFilter={noop} onSelect={noop} onFallbackSelect={noop} onRead={noop} onUse={noop} onRemove={noop}
    {...extra}
  />
);

beforeAll(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-09-30T12:00:00Z"));
});
afterAll(() => vi.useRealTimers());

test.each(["vault/default", "vault/fresh-selected", "vault/web", "vault/failed-query", "vault/empty"])("%s", (id) => {
  const c = fixtureCase(id);
  // vault/default: the reference falls back to the first row because caesar_cipher isn't in the vault yet.
  expectParity(ssr(view(c.state)), c.html!);
});

test("the caesar-forge vault page (fresh tool with its source)", () => {
  const s = snap("caesar-forge", "vault");
  const tools = s.vault as VaultTool[];
  expectParity(ssr(view({ tools, selected: "caesar_cipher", stagger: true, source: SOURCES.caesar_cipher })), innerOf(s.regions["#view-vault"]!, "#view-vault"));
});

test("the remove button asks first", () => {
  const onRemove = vi.fn();
  const s = snap("vault-browse", "confirm");
  const tools = s.vault as VaultTool[];
  expectParity(ssr(view({ tools, filter: "failed", selected: "flatten_json" }, { confirmRemove: "flatten_json" })), innerOf(s.regions["#view-vault"]!, "#view-vault"));
  render(view({ tools, selected: "flatten_json" }, { onRemove }));
  fireEvent.click(screen.getByText("Remove from vault"));
  expect(onRemove).toHaveBeenCalledWith("flatten_json");
});

test("search, filters, selection, read and use call back", () => {
  const onQuery = vi.fn();
  const onFilter = vi.fn();
  const onSelect = vi.fn();
  const onUse = vi.fn();
  const tools = fixtureCase("vault/default").state.tools as VaultTool[];
  render(view({ tools, selected: "hex_to_rgb" }, { onQuery, onFilter, onSelect, onUse }));
  fireEvent.input(screen.getByPlaceholderText("Search by name or keyword"), { target: { value: "hex" } });
  fireEvent.click(screen.getByText("Uses the web"));
  fireEvent.click(screen.getByText("slugify"));
  fireEvent.click(screen.getByText("Use in a question"));
  expect(onQuery).toHaveBeenCalledWith("hex");
  expect(onFilter).toHaveBeenCalledWith("web");
  expect(onSelect).toHaveBeenCalledWith("slugify");
  expect(onUse).toHaveBeenCalledWith("hex_to_rgb");
});

test("live mode (demo=false) never shows the demo's source line, demo mode does", () => {
  const tools = [{ name: "t", args: "x", ret: "str", desc: "d", kw: [], uses: 0, fails: 0, streak: 0, created: "2026-09-30T10:00:00.000Z", last: "", lastFail: "", lastFailAt: "", web: false, fresh: false }];
  for (const demo of [true, false]) {
    const { container, unmount } = render(view({ tools, selected: "t" }, { demo }));
    expect(container.textContent?.includes("This demo only bundles")).toBe(demo);
    unmount();
  }
});

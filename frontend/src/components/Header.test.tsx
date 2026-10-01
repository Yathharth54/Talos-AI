import { fireEvent, render, screen } from "@testing-library/react";
import { expectParity, fixtureCase, snap } from "../test/parity";
import { ssr } from "../test/ssr";
import type { View } from "../store/types";
import { Header, type HeaderProps } from "./Header";

const props = (s: Record<string, unknown>): HeaderProps => ({
  mode: "demo", busy: !!s.busy, badge: !!s.badge, view: (s.view as View) ?? "workbench", model: "deepseek/deepseek-v4.1-flash",
  popOpen: !!s.popOpen, speed: (s.speed as number) ?? 1, onTogglePop: () => {}, onSpeed: () => {}, onReset: () => {},
});

test.each(["header/default", "header/busy-badge-pop"])("%s matches the reference", (id) => {
  const c = fixtureCase(id);
  expectParity(ssr(<Header {...props(c.state)} />), c.html!);
});

test.each([["open", { popOpen: true, speed: 1 }], ["fast", { popOpen: true, speed: 2 }], ["closed", { popOpen: false, speed: 2 }]] as const)(
  "demo controls %s",
  (name, s) => {
    expectParity(ssr(<Header {...props(s)} />), snap("demo-controls", name).regions["header.top"]!);
  },
);

test("live mode has no Demo controls", () => {
  render(<Header {...props({})} mode="live" />);
  expect(screen.queryByText("Demo controls")).toBeNull();
  expect(screen.getByText("deepseek/deepseek-v4.1-flash")).toBeInTheDocument();
});

test("the popover opens, picks a speed, resets, and closes on Escape or an outside click", () => {
  const onTogglePop = vi.fn();
  const onSpeed = vi.fn();
  const onReset = vi.fn();
  render(<Header {...props({ popOpen: true })} onTogglePop={onTogglePop} onSpeed={onSpeed} onReset={onReset} />);
  fireEvent.click(screen.getByText("Fast"));
  expect(onSpeed).toHaveBeenCalledWith(2);
  fireEvent.click(screen.getByText("Reset the demo"));
  expect(onReset).toHaveBeenCalled();
  fireEvent.keyDown(document, { key: "Escape" });
  expect(onTogglePop).toHaveBeenCalledWith(false);
  onTogglePop.mockClear();
  fireEvent.click(document.body);
  expect(onTogglePop).toHaveBeenCalledWith(false);
  onTogglePop.mockClear();
  fireEvent.click(screen.getByText("Demo controls"));
  expect(onTogglePop).toHaveBeenCalledTimes(1);
  expect(onTogglePop).toHaveBeenLastCalledWith();
});

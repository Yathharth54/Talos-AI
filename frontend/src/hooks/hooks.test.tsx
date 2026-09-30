import { act, fireEvent, render, screen } from "@testing-library/react";
import { useRef, useState } from "react";
import { setReducedMotion } from "../test/media";
import { useFocusTrap } from "./useFocusTrap";
import { usePointerGlow } from "./usePointerGlow";
import { useRestartAnimation } from "./useRestartAnimation";
import { useScramble } from "./useScramble";
import { useStaleViewScroll } from "./useStaleViewScroll";
import { useTabIndicator } from "./useTabIndicator";

afterEach(() => vi.useRealTimers());

function Title({ text }: { text: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  useScramble(ref, text, 600);
  return <span data-testid="t" ref={ref} dangerouslySetInnerHTML={{ __html: text }} />;
}

test("useScramble decodes new text into place and settles on it", () => {
  setReducedMotion(false);
  vi.useFakeTimers({ toFake: ["requestAnimationFrame", "performance"] });
  const { rerender } = render(<Title text="Session 1" />);
  expect(screen.getByTestId("t").textContent).toBe("Session 1");
  rerender(<Title text="Caesar cipher" />);
  act(() => void vi.advanceTimersByTime(100));
  expect(screen.getByTestId("t").textContent).not.toBe("Caesar cipher");
  act(() => void vi.advanceTimersByTime(700));
  expect(screen.getByTestId("t").textContent).toBe("Caesar cipher");
});

function Panel({ tab }: { tab: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useRestartAnimation(ref, "panel-in", tab);
  return <div data-testid="p" className="stack" ref={ref} />;
}

test("useRestartAnimation adds the class on change, not on mount", () => {
  const { rerender } = render(<Panel tab="log" />);
  expect(screen.getByTestId("p").className).toBe("stack");
  rerender(<Panel tab="code" />);
  expect(screen.getByTestId("p").className).toBe("stack panel-in");
});

function Tabs() {
  const [sel, setSel] = useState("a");
  const ref = useRef<HTMLDivElement>(null);
  useTabIndicator(ref, sel, "run-1");
  return (
    <div className="tabs" ref={ref}>
      <button className="tab" aria-selected={sel === "a"} onClick={() => setSel("a")}>A</button>
      <button className="tab" aria-selected={sel === "b"} onClick={() => setSel("b")}>B</button>
      <span className="tab-ind" data-testid="ind" />
    </div>
  );
}

test("useTabIndicator places the indicator under the selected tab", () => {
  const offsets = vi.spyOn(HTMLElement.prototype, "offsetLeft", "get").mockImplementation(function (this: HTMLElement) {
    return this.textContent === "B" ? 60 : 0;
  });
  const widths = vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockReturnValue(50);
  render(<Tabs />);
  expect(screen.getByTestId("ind").style.left).toBe("0px");
  fireEvent.click(screen.getByText("B"));
  expect(screen.getByTestId("ind").style.left).toBe("60px");
  expect(screen.getByTestId("ind").style.width).toBe("50px");
  offsets.mockRestore();
  widths.mockRestore();
});

function Dialog({ onEscape }: { onEscape: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useFocusTrap(ref, { onEscape, initialFocus: '[data-d="no"]' });
  return (
    <div ref={ref}>
      <button data-d="no">Don't run</button>
      <button data-d="yes">Run code</button>
    </div>
  );
}

test("useFocusTrap focuses, traps Tab, handles Escape and restores focus", () => {
  const outside = document.createElement("button");
  document.body.append(outside);
  outside.focus();
  const onEscape = vi.fn();
  const { unmount } = render(<Dialog onEscape={onEscape} />);
  expect(document.activeElement).toBe(screen.getByText("Don't run"));
  fireEvent.keyDown(document.activeElement!, { key: "Tab", shiftKey: true });
  expect(document.activeElement).toBe(screen.getByText("Run code"));
  fireEvent.keyDown(document.activeElement!, { key: "Tab" });
  expect(document.activeElement).toBe(screen.getByText("Don't run"));
  fireEvent.keyDown(document.activeElement!, { key: "Escape" });
  expect(onEscape).toHaveBeenCalledTimes(1);
  unmount();
  expect(document.activeElement).toBe(outside);
  outside.remove();
});

function Glow() {
  usePointerGlow();
  return <button className="try" data-testid="card"><span className="q">x</span></button>;
}

test("usePointerGlow sets --mx and --my on the card under the pointer", () => {
  render(<Glow />);
  const card = screen.getByTestId("card");
  vi.spyOn(card, "getBoundingClientRect").mockReturnValue({ left: 10, top: 20 } as DOMRect);
  fireEvent.pointerMove(card.firstChild!, { clientX: 50, clientY: 70 });
  expect(card.style.getPropertyValue("--mx")).toBe("40px");
  expect(card.style.getPropertyValue("--my")).toBe("50px");
});

function View({ name, view, enter }: { name: string; view: string; enter: number }) {
  const ref = useRef<HTMLElement>(null);
  useStaleViewScroll(ref, view === name, enter, name !== "wb");
  return <section data-testid={name} hidden={view !== name} ref={ref} />;
}

function Views({ view, enter }: { view: string; enter: number }) {
  return (
    <div data-testid="views">
      <View name="wb" view={view} enter={enter} />
      <View name="sessions" view={view} enter={enter} />
    </div>
  );
}

test("useStaleViewScroll clamps .views to the height of the view's last render, as showView's reflow does", () => {
  const { rerender } = render(<Views view="wb" enter={0} />);
  const views = screen.getByTestId("views");
  let top = 0;
  Object.defineProperty(views, "scrollTop", { get: () => top, set: (v: number) => void (top = v), configurable: true });
  Object.defineProperty(views, "clientHeight", { value: 784, configurable: true });
  Object.defineProperty(screen.getByTestId("sessions"), "offsetHeight", { value: 1344, configurable: true });

  // First visit: the reflow sees the empty markup, so the scroll goes to the top.
  top = 709;
  rerender(<Views view="sessions" enter={1} />);
  expect(top).toBe(0);

  // Back to the workbench: it's live in the reference, so the browser's own clamp applies.
  top = 709;
  rerender(<Views view="wb" enter={2} />);
  expect(top).toBe(709);

  // Second visit: clamped to the last render's height (1344 - 784).
  rerender(<Views view="sessions" enter={3} />);
  expect(top).toBe(560);

  // Already inside the range: untouched.
  top = 100;
  rerender(<Views view="wb" enter={4} />);
  rerender(<Views view="sessions" enter={5} />);
  expect(top).toBe(100);
});

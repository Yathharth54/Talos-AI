import { act, fireEvent, render, screen } from "@testing-library/react";
import { SOURCES } from "../../demo/data";
import { expectParity, fixtureCase, snap } from "../../test/parity";
import { innerOf, ssr } from "../../test/ssr";
import type { DialogReq } from "../../store/types";
import { ModalRoot } from "./ModalRoot";

const noop = () => {};
const modal = (dialog: DialogReq) => ssr(<ModalRoot dialog={dialog} demo onApproval={noop} onKey={noop} onClose={noop} />);

test.each([["dialog/approval-python", "python_exec"], ["dialog/approval-shell", "shell_exec"]] as const)("%s", (id, tool) => {
  const c = fixtureCase(id);
  expectParity(modal({ kind: "approval", runId: "r", tool, code: c.state.code as string }), c.html!);
});

test("dialog/key and dialog/reader-caesar", () => {
  const k = fixtureCase("dialog/key");
  expectParity(modal({ kind: "key", runId: "r", toolName: "get_current_temperature", envVar: "OPENWEATHERMAP_API_KEY", service: "OpenWeatherMap" }), k.html!);
  const r = fixtureCase("dialog/reader-caesar");
  expectParity(modal({ kind: "reader", name: "caesar_cipher", lines: SOURCES.caesar_cipher! }), r.html!);
});

test("Escape cancels and restores focus", () => {
  const before = document.createElement("button");
  document.body.append(before);
  before.focus();
  const onApproval = vi.fn();
  const { unmount } = render(<ModalRoot dialog={{ kind: "approval", runId: "r", tool: "python_exec", code: "print(1)" }} demo onApproval={onApproval} onKey={noop} onClose={noop} />);
  expect(document.activeElement).toBe(screen.getByText("Don't run"));
  fireEvent.keyDown(document.activeElement!, { key: "Escape" });
  expect(onApproval).toHaveBeenCalledWith("cancel");
  unmount();
  expect(document.activeElement).toBe(before);
  before.remove();
});

test("approval answers; the Settings link declines", () => {
  const onApproval = vi.fn();
  render(<ModalRoot dialog={{ kind: "approval", runId: "r", tool: "python_exec", code: "print(1)" }} demo onApproval={onApproval} onKey={noop} onClose={noop} />);
  fireEvent.click(screen.getByText("Run code"));
  fireEvent.click(screen.getByText("Ask before running code"));
  expect(onApproval.mock.calls).toEqual([["yes"], ["no"]]);
});

test("the key dialog asks for a key before saving, and skips", () => {
  const onKey = vi.fn();
  const { container } = render(<ModalRoot dialog={{ kind: "key", runId: "r", toolName: "get_current_temperature", envVar: "OPENWEATHERMAP_API_KEY", service: "OpenWeatherMap" }} demo onApproval={noop} onKey={onKey} onClose={noop} />);
  fireEvent.click(screen.getByText("Save key"));
  expect(onKey).not.toHaveBeenCalled();
  expectParity(container.innerHTML, innerOf(snap("weather-save", "dialog-error").regions["#modal-root"]!, "#modal-root"));
  expect(document.activeElement).toBe(container.querySelector("#dlg-key"));
  fireEvent.change(container.querySelector("#dlg-key")!, { target: { value: "  owm-key  " } });
  fireEvent.click(screen.getByText("Save key"));
  fireEvent.click(screen.getByText("Skip"));
  expect(onKey.mock.calls).toEqual([[{ action: "save", value: "owm-key" }], [{ action: "skip" }]]);
});

test("the reader copies, falls back, and closes on a click outside", async () => {
  vi.useFakeTimers();
  const onClose = vi.fn();
  const writeText = vi.fn().mockRejectedValue(new Error("denied"));
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
  const { container } = render(<ModalRoot dialog={{ kind: "reader", name: "caesar_cipher", lines: ["a", "b"] }} demo onApproval={noop} onKey={noop} onClose={onClose} />);
  await act(async () => void fireEvent.click(screen.getByText("Copy")));
  expect(writeText).toHaveBeenCalledWith("a\nb");
  expect(screen.getByText("Selected, press Ctrl+C")).toBeInTheDocument();
  act(() => void vi.advanceTimersByTime(1800));
  expect(screen.getByText("Copy")).toBeInTheDocument();
  fireEvent.click(container.querySelector("#scrim")!);
  expect(onClose).toHaveBeenCalled();
  vi.useRealTimers();
});

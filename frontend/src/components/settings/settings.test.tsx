import { fireEvent, render, screen } from "@testing-library/react";
import { expectParity, fixtureCase } from "../../test/parity";
import { ssr } from "../../test/ssr";
import { SettingsView } from "./SettingsView";

test.each(["settings/default", "settings/off-key"])("%s", (id) => {
  const c = fixtureCase(id);
  const s = c.state as { askExec: boolean; env: Record<string, string> };
  expectParity(ssr(<SettingsView askExec={s.askExec} env={s.env} model="deepseek/deepseek-v4.1-flash" onToggleAsk={() => {}} />), c.html!);
});

test("the switch toggles and keeps focus", () => {
  const onToggleAsk = vi.fn();
  render(<SettingsView askExec env={{}} model="m" onToggleAsk={onToggleAsk} />);
  const sw = screen.getByRole("switch");
  fireEvent.click(sw);
  expect(onToggleAsk).toHaveBeenCalled();
  expect(document.activeElement).toBe(sw);
});

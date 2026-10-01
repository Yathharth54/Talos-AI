import { readRef } from "../../scripts/reference.mjs";
import { CAESAR, MODEL, SOURCES, SUGGESTIONS, USE_PRESETS, VAULT_ROWS, WEATHER } from "./data";

test("demo data is the reference's, verbatim", () => {
  const ref = readRef();
  for (const s of SUGGESTIONS) {
    expect(ref).toContain(s.q);
    expect(ref).toContain(s.what);
  }
  expect(SUGGESTIONS.map((s) => !!s.forge)).toEqual([true, false, false, true]);
  for (const m of [CAESAR, WEATHER]) {
    expect(ref).toContain(`name: "${m.name}", args: "${m.args}"`);
    expect(ref).toContain(`desc: "${m.desc}"`);
    expect(ref).toContain(`kw: ${JSON.stringify(m.kw).replace(/","/g, '", "')}`);
  }
  for (const v of Object.values(USE_PRESETS)) expect(ref).toContain(v);
  expect(ref).toContain(MODEL);
  expect(SOURCES.caesar_cipher).toHaveLength(63);
  expect(SOURCES.get_current_temperature).toHaveLength(36);
  expect(VAULT_ROWS).toHaveLength(40);
});

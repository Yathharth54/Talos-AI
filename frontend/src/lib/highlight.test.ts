import data from "../demo/reference-data.json";
import { fixtureCase } from "../test/parity";
import { highlight } from "./highlight";

test("highlight() matches the reference function on caesar_cipher.py", () => {
  const lines = data.sources["src-caesar"].split("\n");
  expect(highlight(lines)).toEqual(fixtureCase("lib/highlight-caesar").value);
});

test("highlight() matches the reference function on get_current_temperature.py", () => {
  const lines = data.sources["src-weather"].split("\n");
  expect(highlight(lines)).toEqual(fixtureCase("lib/highlight-weather").value);
});

test("docstrings are one string span per line and keywords are marked", () => {
  const out = highlight(['def f(x):', '    """Doc', '    more"""', '    return None']);
  expect(out[0]).toBe('<span class="kw">def</span> f(x):');
  expect(out[1]).toBe('<span class="str">    &quot;&quot;&quot;Doc</span>');
  expect(out[2]).toBe('<span class="str">    more&quot;&quot;&quot;</span>');
  expect(out[3]).toBe('    <span class="kw">return</span> <span class="kw">None</span>');
});

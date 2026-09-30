import { sanitize } from "./sanitize";

test("keeps the contract's allowlist: mono and gold spans, in-app links", () => {
  const html = 'Attempt <span class="gold">2 of 3.</span> <span class="mono">caesar_cipher</span> <a href="#vault">the Vault</a> <a href="#settings">Settings</a>';
  expect(sanitize(html)).toBe(html);
});

test("drops every other element to its text and escapes it", () => {
  expect(sanitize('<script>alert(1)</script><b>bold</b> <img src=x onerror="x()">')).toBe("alert(1)bold ");
  expect(sanitize('<a href="https://evil.example">x</a>')).toBe("x");
  expect(sanitize('<span class="mono" onclick="x()">y</span>')).toBe("y");
  expect(sanitize('<span class="other">z</span>')).toBe("z");
});

test("keeps entities escaped", () => {
  expect(sanitize("&lt;b&gt; &amp; &quot;q&quot;")).toBe("&lt;b&gt; &amp; &quot;q&quot;");
});

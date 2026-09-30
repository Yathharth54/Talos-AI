import { ApiError, createApi } from "./api";

const reply = (status: number, body?: unknown) =>
  Promise.resolve(new Response(body === undefined ? null : JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));

test("sends JSON to /api and returns the body", async () => {
  const f = vi.fn(() => reply(202, { run: { id: "r", n: 1 }, message: { id: "m" } }));
  const api = createApi(f as unknown as typeof fetch);
  const out = await api.send("s1", "hello");
  expect(out.run.id).toBe("r");
  expect(f).toHaveBeenCalledWith("/api/sessions/s1/messages", expect.objectContaining({ method: "POST", body: JSON.stringify({ text: "hello" }) }));
});

test("204 resolves to undefined; names are URL-encoded", async () => {
  const f = vi.fn(() => Promise.resolve(new Response(null, { status: 204 })));
  await expect(createApi(f as unknown as typeof fetch).removeTool("a b")).resolves.toBeUndefined();
  expect(f).toHaveBeenCalledWith("/api/vault/a%20b", expect.objectContaining({ method: "DELETE" }));
});

test("errors carry stage 2's code, message and run_active ids", async () => {
  const body = { error: { code: "run_active", message: "A run is already going. Stop it or wait for it to finish.", run_id: "r9", session_id: "s9" } };
  const api = createApi((() => reply(409, body)) as unknown as typeof fetch);
  const err = await api.send("s1", "x").catch((e: unknown) => e);
  expect(err).toBeInstanceOf(ApiError);
  expect(err).toMatchObject({ status: 409, code: "run_active", runId: "r9", sessionId: "s9" });
});

test("resume sends the decision and nothing else", async () => {
  const f = vi.fn(() => reply(202, { ok: true }));
  await createApi(f as unknown as typeof fetch).resume("r", { decision: "save", value: "k" });
  expect(f).toHaveBeenCalledWith("/api/runs/r/resume", expect.objectContaining({ body: '{"decision":"save","value":"k"}' }));
});

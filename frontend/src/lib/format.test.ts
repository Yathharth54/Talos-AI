import { argNames, esc, fmtClock, fmtDay, fmtShort, fmtTime, nowIso, pyRepr, pyStr, sameDay, splitArgs } from "./format";
import { FIXED_NOW } from "../test/parity";

afterEach(() => vi.useRealTimers());

test("fmtTime, fmtClock, fmtShort, fmtDay", () => {
  expect(fmtTime("")).toBe("Never");
  expect(fmtTime(null)).toBe("Never");
  expect(fmtTime("2026-09-28T14:20")).toBe("28 Sep 2026, 14:20");
  expect(fmtClock("2026-09-28T09:05")).toBe("09:05");
  expect(fmtShort("2026-09-28T14:44")).toBe("28 Sep, 14:44");
  expect(fmtDay("2026-09-28T14:20")).toBe("28 Sep 2026");
});

test("nowIso and sameDay use the local clock", () => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(FIXED_NOW));
  expect(nowIso()).toBe("2026-09-30T12:00");
  expect(sameDay("2026-09-30T08:00")).toBe(true);
  expect(sameDay("2026-09-28T14:20")).toBe(false);
});

test("splitArgs keeps brackets together and argNames keeps only names", () => {
  expect(splitArgs("headers: list[str], rows: list[list[str]]")).toEqual(["headers: list[str]", "rows: list[list[str]]"]);
  expect(splitArgs("a: tuple[int, int], b: dict")).toEqual(["a: tuple[int, int]", "b: dict"]);
  expect(splitArgs("")).toEqual([]);
  expect(argNames("lat1: float, lon1: float, lat2: float, lon2: float")).toBe("lat1, lon1, lat2, lon2");
  expect(argNames("code: str, timeout: int | None = None")).toBe("code, timeout");
});

test("esc, pyRepr, pyStr", () => {
  expect(esc(`<a href="x">it's & </a>`)).toBe("&lt;a href=&quot;x&quot;&gt;it&#39;s &amp; &lt;/a&gt;");
  expect(pyRepr("TALOS")).toBe('"TALOS"');
  expect(pyRepr(7)).toBe("7");
  expect(pyStr("AHSVZ HNLUA")).toBe("'AHSVZ HNLUA'");
  expect(pyStr("it's")).toBe("'it\\'s'");
});

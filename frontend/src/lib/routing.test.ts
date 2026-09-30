import { caesar, classify, parseCaesar, provisionalVariant, runPython, sessionName } from "./routing";

const Q = {
  forge: 'Build a Caesar cipher tool that can both encrypt and decrypt. Encrypt "TALOS AGENT" with a shift of 7.',
  reuse: 'Decrypt this Caesar cipher message with shift 7: "AHSVZ HNLUA"',
  wordShift: 'Decrypt this Caesar cipher message with shift seven: "AHSVZ HNLUA"',
  python: "Run this Python code and give me the output: print(sum(range(1, 101)))",
  weather: "Use the OpenWeatherMap API to get the current temperature in Mumbai.",
};

test("caesar", () => {
  expect(caesar("TALOS AGENT", 7, "encrypt")).toBe("AHSVZ HNLUA");
  expect(caesar("AHSVZ HNLUA", 7, "decrypt")).toBe("TALOS AGENT");
  expect(caesar("xyz, XYZ!", 3, "encrypt")).toBe("abc, ABC!");
  expect(caesar("abc", -1, "encrypt")).toBe("zab");
  expect(caesar("abc", 27, "encrypt")).toBe("bcd");
});

test("parseCaesar", () => {
  expect(parseCaesar(Q.forge)).toEqual({ text: "TALOS AGENT", shift: 7, shiftWord: null, mode: "encrypt" });
  expect(parseCaesar(Q.reuse)).toEqual({ text: "AHSVZ HNLUA", shift: 7, shiftWord: null, mode: "decrypt" });
  expect(parseCaesar(Q.wordShift)).toEqual({ text: "AHSVZ HNLUA", shift: 7, shiftWord: "seven", mode: "decrypt" });
  expect(parseCaesar("Encrypt “hi there” with shift of 3")).toEqual({ text: "hi there", shift: 3, shiftWord: null, mode: "encrypt" });
  expect(parseCaesar("decrypt with a caesar cipher")).toEqual({ text: "AHSVZ HNLUA", shift: 7, shiftWord: null, mode: "decrypt" });
  expect(parseCaesar("shift to the right, caesar")).toMatchObject({ shift: 7, shiftWord: null });
});

test("classify", () => {
  expect(classify("What can you do?")).toBe("chat");
  expect(classify(Q.forge)).toBe("caesar");
  expect(classify(Q.python)).toBe("python");
  expect(classify(Q.weather)).toBe("weather");
  expect(classify("How many tools are in your vault?")).toBe("vaultlist");
  expect(classify("Summarise this PDF")).toBe("unknown");
});

test("runPython", () => {
  expect(runPython("print(sum(range(1, 101)))")).toBe("5050");
  expect(runPython('print("hi")')).toBe("hi");
  expect(runPython("print(2 * (3 + 4))")).toBe("14");
  expect(runPython("print(open('x'))")).toBeNull();
  expect(runPython("import os")).toBeNull();
});

test("sessionName", () => {
  expect(sessionName("caesar", Q.forge)).toBe("Caesar cipher");
  expect(sessionName("python", Q.python)).toBe("Running Python");
  expect(sessionName("weather", Q.weather)).toBe("Weather in Mumbai");
  expect(sessionName("weather", "What's the temperature in New York?")).toBe("Weather in New York");
  expect(sessionName("chat", "What can you do?")).toBe("Getting to know Talos");
  expect(sessionName("vaultlist", "How many tools")).toBe("What's in the vault");
  expect(sessionName("unknown", "summarise <b>this</b> PDF & more")).toBe("Summarise <b>this</b> PDF &");
});

test("provisionalVariant mirrors the reference's first strip", () => {
  expect(provisionalVariant(Q.forge, [])).toBe("forge");
  expect(provisionalVariant(Q.reuse, ["caesar_cipher"])).toBe("vault");
  expect(provisionalVariant(Q.weather, [])).toBe("forge");
  expect(provisionalVariant(Q.weather, ["get_current_temperature"])).toBe("vault");
  expect(provisionalVariant(Q.python, [])).toBe("primitive");
  expect(provisionalVariant("How many tools are in your vault?", [])).toBe("primitive");
  expect(provisionalVariant("What can you do?", [])).toBe("chat");
  expect(provisionalVariant("Summarise this", [])).toBe("chat");
});

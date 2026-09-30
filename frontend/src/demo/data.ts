import ref from "./reference-data.json";

export interface ToolMeta {
  name: string;
  args: string;
  ret: string;
  desc: string;
  kw: string[];
  env?: string;
  web?: boolean;
}
export type VaultRow = [string, string, string, string, string[], number, number, number, string, string, string];

export const MODEL = "deepseek/deepseek-v4.1-flash";
export const VAULT_ROWS = ref.vaultData as VaultRow[];

export const CAESAR: ToolMeta = {
  name: "caesar_cipher",
  args: "text: str, shift: int, mode: str",
  ret: "str",
  desc: "Encrypts or decrypts a text string using a Caesar cipher with a given shift, preserving case and non-alphabetic characters.",
  kw: ["caesar", "cipher", "encrypt", "decrypt", "shift", "text", "cryptography"],
};
export const WEATHER: ToolMeta = {
  name: "get_current_temperature",
  args: "city: str",
  ret: "float",
  desc: "Returns the current temperature in Celsius for a city from OpenWeatherMap.",
  kw: ["weather", "temperature", "openweathermap", "city", "celsius", "mumbai"],
  env: "OPENWEATHERMAP_API_KEY",
  web: true,
};

/** Bundled sources, by tool name. The reference's getSource() splits on "\n" (line 1309). */
export const SOURCES: Record<string, string[]> = {
  caesar_cipher: ref.sources["src-caesar"].split("\n"),
  get_current_temperature: ref.sources["src-weather"].split("\n"),
};

export const SUGGESTIONS: { q: string; what: string; forge?: boolean }[] = [
  { q: 'Build a Caesar cipher tool that can both encrypt and decrypt. Encrypt "TALOS AGENT" with a shift of 7.', what: "Forges a new tool", forge: true },
  { q: 'Decrypt this Caesar cipher message with shift 7: "AHSVZ HNLUA"', what: "Reuses it once it's in the vault" },
  { q: "Run this Python code and give me the output: print(sum(range(1, 101)))", what: "Built in, asks before it runs code" },
  { q: "Use the OpenWeatherMap API to get the current temperature in Mumbai.", what: "Forges a tool that needs an API key", forge: true },
];

/** "Use in a question" prefills (line 2119); other tools get COPY.vault.usePrefill. */
export const USE_PRESETS: Record<string, string> = {
  caesar_cipher: 'Decrypt this Caesar cipher message with shift 7: "AHSVZ HNLUA"',
  get_current_temperature: "Use the OpenWeatherMap API to get the current temperature in Mumbai.",
};

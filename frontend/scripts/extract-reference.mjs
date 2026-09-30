import { writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { extractStyle, extractTextScript, extractVaultData, readRef } from "./reference.mjs";

const ref = readRef();
writeFileSync(resolve(process.cwd(), "src/styles.css"), extractStyle(ref));
const data = {
  vaultData: extractVaultData(ref),
  sources: {
    "src-caesar": extractTextScript(ref, "src-caesar"),
    "src-weather": extractTextScript(ref, "src-weather"),
  },
};
writeFileSync(resolve(process.cwd(), "src/demo/reference-data.json"), JSON.stringify(data, null, 1) + "\n");
console.log("wrote src/styles.css and src/demo/reference-data.json");

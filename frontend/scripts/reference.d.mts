export type VaultRow = [
  name: string, args: string, ret: string, desc: string, kw: string[],
  uses: number, fails: number, streak: number, created: string, last: string, lastFail: string,
];
export declare const REF_DIR: string;
export declare const REF_BODY: string;
export declare const REF_INDEX: string;
export declare const REF_ASSETS: string;
export declare function readRef(): string;
export declare function extractStyle(ref: string): string;
export declare function extractTextScript(ref: string, id: string): string;
export declare function extractVaultData(ref: string): VaultRow[];

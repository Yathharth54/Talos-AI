import { useRef, useState } from "react";
import { useFocusTrap } from "../../hooks/useFocusTrap";
import { COPY, fill } from "../../lib/copy";

export type KeyAnswer = { action: "save"; value: string } | { action: "skip" } | { action: "cancel" };

export interface KeyDialogProps {
  toolName: string;
  envVar: string;
  service: string;
  /** Adds the demo's "keeps the key in memory only" sentence to the footer. */
  demo: boolean;
  onAnswer(a: KeyAnswer): void;
}

/** The API key dialog (keyDialog, lines 1391–1420). */
export function KeyDialog({ toolName, envVar, service, demo, onAnswer }: KeyDialogProps) {
  const ref = useRef<HTMLFormElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const [error, setError] = useState("");
  useFocusTrap(ref, { onEscape: () => onAnswer({ action: "cancel" }), initialFocus: "#dlg-key" });
  return (
    <form
      className="dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby="dlg-t"
      noValidate
      ref={ref}
      onSubmit={(e) => {
        e.preventDefault();
        const v = (inputRef.current?.value ?? "").trim();
        if (!v) {
          setError(COPY.key.error);
          inputRef.current?.focus();
          return;
        }
        onAnswer({ action: "save", value: v });
      }}
    >
      <div className="d-top">
        <span className="eyebrow">{COPY.key.eyebrow}</span>
        <h2 id="dlg-t">{fill(COPY.key.title, { service })}</h2>
        <p>
          <span className="mono" style={{ fontSize: "14px", color: "var(--bone)" }}>
            {toolName}
          </span>
          {COPY.key.body}
        </p>
      </div>
      <div className="field">
        <label htmlFor="dlg-key">{envVar}</label>
        <input id="dlg-key" type="password" autoComplete="off" placeholder={COPY.key.placeholder} aria-describedby="dlg-err" ref={inputRef} />
        <span className="err" id="dlg-err" aria-live="polite">
          {error}
        </span>
      </div>
      <div className="d-act">
        <button type="button" className="pill ghost lg" data-d="skip" onClick={() => onAnswer({ action: "skip" })}>
          {COPY.key.skip}
        </button>
        <button type="submit" className="pill solid lg">
          {COPY.key.save}
        </button>
      </div>
      <p className="d-foot">{demo ? COPY.key.foot + COPY.key.footDemo : COPY.key.foot}</p>
    </form>
  );
}

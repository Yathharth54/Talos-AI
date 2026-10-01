import type { Ref } from "react";
import { COPY } from "../../lib/copy";

export interface ComposerProps {
  value: string;
  disabled: boolean;
  hint: string;
  busy: boolean;
  onChange(v: string): void;
  onSubmit(): void;
  inputRef?: Ref<HTMLTextAreaElement>;
}

/** The composer (lines 638–645; setBusy 1501–1506, updateComposer 1507–1514, keydown 2093). */
export function Composer({ value, disabled, hint, busy, onChange, onSubmit, inputRef }: ComposerProps) {
  return (
    <form
      className="composer"
      id="composer"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit();
      }}
    >
      <label htmlFor="ask">{COPY.convo.askLabel}</label>
      <textarea
        id="ask"
        rows={3}
        placeholder={COPY.convo.placeholder}
        value={value}
        disabled={disabled}
        ref={inputRef}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            e.currentTarget.form?.requestSubmit();
          }
        }}
      />
      <div className="composer-row">
        <span className="hint" id="composer-hint">
          {hint}
        </span>
        <button type="submit" className="pill solid" id="send" disabled={disabled}>
          {busy ? COPY.convo.working : COPY.convo.send}
        </button>
      </div>
    </form>
  );
}

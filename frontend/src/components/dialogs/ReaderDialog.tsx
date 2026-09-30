import { useEffect, useRef, useState } from "react";
import { useFocusTrap } from "../../hooks/useFocusTrap";
import { COPY, fill } from "../../lib/copy";
import { CodeRows } from "../vault/CodeRows";

/** The full-source reader (readerDialog, lines 2016–2040; codeRows, line 2015). */
export function ReaderDialog({ name, lines, onClose }: { name: string; lines: string[]; onClose(): void }) {
  const ref = useRef<HTMLDivElement>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  const [copyLabel, setCopyLabel] = useState<string>(COPY.reader.copy);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useFocusTrap(ref, { onEscape: onClose, initialFocus: '[data-r="close"]' });
  useEffect(() => () => clearTimeout(timer.current), []);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(lines.join("\n"));
      setCopyLabel(COPY.reader.copied);
    } catch {
      const body = bodyRef.current;
      const sel = window.getSelection();
      if (body && sel) {
        const range = document.createRange();
        range.selectNodeContents(body);
        sel.removeAllRanges();
        sel.addRange(range);
      }
      setCopyLabel(COPY.reader.selected);
    }
    timer.current = setTimeout(() => setCopyLabel(COPY.reader.copy), 1800);
  };

  return (
    <div className="dialog reader" role="dialog" aria-modal="true" aria-labelledby="rd-t" ref={ref}>
      <div className="r-head">
        <div style={{ minWidth: "0" }}>
          <h2 id="rd-t">{fill(COPY.reader.title, { name })}</h2>
          <p>{fill(COPY.reader.sub, { n: lines.length })}</p>
        </div>
        <div className="r-act">
          <button type="button" className="pill ghost sm" data-r="copy" onClick={() => void copy()}>
            {copyLabel}
          </button>
          <button type="button" className="pill solid sm" data-r="close" onClick={onClose}>
            {COPY.reader.close}
          </button>
        </div>
      </div>
      <div className="code-body" tabIndex={0} aria-label={COPY.reader.aria} ref={bodyRef}>
        <CodeRows lines={lines} />
      </div>
    </div>
  );
}

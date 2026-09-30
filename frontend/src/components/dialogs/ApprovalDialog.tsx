import { useRef } from "react";
import { useFocusTrap } from "../../hooks/useFocusTrap";
import { COPY, fill } from "../../lib/copy";

export type ApprovalAnswer = "yes" | "no" | "cancel";

/** The exec approval dialog (approvalDialog, lines 1368–1390). */
export function ApprovalDialog({ tool, code, onAnswer }: { tool: "python_exec" | "shell_exec"; code: string; onAnswer(a: ApprovalAnswer): void }) {
  const ref = useRef<HTMLDivElement>(null);
  useFocusTrap(ref, { onEscape: () => onAnswer("cancel"), initialFocus: '[data-d="no"]' });
  const shell = tool === "shell_exec";
  return (
    <div className="dialog" role="dialog" aria-modal="true" aria-labelledby="dlg-t" aria-describedby="dlg-d" ref={ref}>
      <div className="d-top">
        <span className="eyebrow">{fill(COPY.approval.eyebrow, { tool })}</span>
        <h2 id="dlg-t">{shell ? COPY.approval.titleShell : COPY.approval.titleCode}</h2>
        <p id="dlg-d">{COPY.approval.body}</p>
      </div>
      <pre>{code}</pre>
      <div className="d-act">
        <button type="button" className="pill ghost lg" data-d="no" onClick={() => onAnswer("no")}>
          {COPY.approval.no}
        </button>
        <button type="button" className="pill solid lg" data-d="yes" onClick={() => onAnswer("yes")}>
          {shell ? COPY.approval.yesShell : COPY.approval.yesCode}
        </button>
      </div>
      <p className="d-foot">
        {COPY.approval.footA}
        {/* Declines and lets the hash change open Settings (line 1386). */}
        <a href="#settings" data-d="settings" onClick={() => onAnswer("no")}>
          {COPY.approval.footLink}
        </a>
        {COPY.approval.footB}
        <span className="mono">{COPY.approval.footVar}</span>
        {COPY.approval.footC}
      </p>
    </div>
  );
}

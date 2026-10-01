import type { DialogReq } from "../../store/types";
import { ApprovalDialog, type ApprovalAnswer } from "./ApprovalDialog";
import { KeyDialog, type KeyAnswer } from "./KeyDialog";
import { ReaderDialog } from "./ReaderDialog";

export interface ModalRootProps {
  dialog: DialogReq | null;
  demo: boolean;
  onApproval(action: ApprovalAnswer): void;
  onKey(r: KeyAnswer): void;
  onClose(): void;
}

/** The scrim and its one dialog, rendered inside App's #modal-root (openDialog, lines 1341–1367). */
export function ModalRoot({ dialog, demo, onApproval, onKey, onClose }: ModalRootProps) {
  if (!dialog) return null;
  let body;
  if (dialog.kind === "approval") body = <ApprovalDialog key={`a-${dialog.runId}`} tool={dialog.tool} code={dialog.code} onAnswer={onApproval} />;
  else if (dialog.kind === "key")
    body = <KeyDialog key={`k-${dialog.runId}`} toolName={dialog.toolName} envVar={dialog.envVar} service={dialog.service} demo={demo} onAnswer={onKey} />;
  else body = <ReaderDialog key={`r-${dialog.name}`} name={dialog.name} lines={dialog.lines} onClose={onClose} />;
  return (
    <div
      className="scrim"
      id="scrim"
      onClick={(e) => {
        // The reader closes on a click on the scrim itself (line 2038).
        if (dialog.kind === "reader" && e.target === e.currentTarget) onClose();
      }}
    >
      {body}
    </div>
  );
}

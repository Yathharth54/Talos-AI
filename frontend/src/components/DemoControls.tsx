import { useEffect } from "react";
import { COPY } from "../lib/copy";

export type DemoControlsProps = {
  popOpen: boolean;
  speed: number;
  onTogglePop(open?: boolean): void;
  onSpeed(speed: number): void;
  onReset(): void;
};

/** Clicks the reference handles earlier in its document listener; they never reach togglePop(false). */
const KEEP_OPEN =
  '[data-suggest], [data-ask], [data-action="stop"], [data-tab], [data-open-tool], [data-run], [data-tool], [data-read-src], [data-use-tool], [data-remove-tool], #ask-switch, [data-speed], #demo-toggle, #demo-reset, #demo-pop';

const SPEEDS: ReadonlyArray<readonly [number, string, string]> = [
  [0.5, "0.5", COPY.demo.slow],
  [1, "1", COPY.demo.normal],
  [2, "2", COPY.demo.fast],
];

/** The Demo controls button and its popover (reference lines 610-622). Demo mode only. */
export function DemoControls({ popOpen, speed, onTogglePop, onSpeed, onReset }: DemoControlsProps) {
  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (!(e.target as Element | null)?.closest?.(KEEP_OPEN)) onTogglePop(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && popOpen) onTogglePop(false);
    };
    document.addEventListener("click", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("click", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [popOpen, onTogglePop]);

  return (
    <div className="demo-btn">
      <button
        type="button"
        className="pill ghost sm"
        id="demo-toggle"
        aria-expanded={String(popOpen) as "true" | "false"}
        aria-controls="demo-pop"
        onClick={() => onTogglePop()}
      >
        {COPY.demo.toggle}
      </button>
      <div className="popover" id="demo-pop" hidden={!popOpen}>
        <p>{COPY.demo.blurb}</p>
        <span className="lbl" id="speed-lbl">{COPY.demo.speed}</span>
        <div className="seg" role="group" aria-labelledby="speed-lbl">
          {SPEEDS.map(([value, attr, label]) => (
            <button
              key={attr}
              type="button"
              className="pill ghost"
              data-speed={attr}
              aria-pressed={String(speed === value) as "true" | "false"}
              onClick={() => onSpeed(value)}
            >
              {label}
            </button>
          ))}
        </div>
        <button
          type="button"
          className="pill ghost"
          id="demo-reset"
          onClick={() => {
            onReset();
            onTogglePop(false);
          }}
        >
          {COPY.demo.reset}
        </button>
      </div>
    </div>
  );
}

import { COPY, fill } from "../../lib/copy";
import { argNames, fmtClock, fmtShort, sameDay } from "../../lib/format";
import type { VaultTool } from "../../store/types";

export interface VaultTableProps {
  rows: VaultTool[];
  selected: string | null;
  stagger: boolean;
  renderKey: number;
  onSelect(name: string): void;
}

/** The `#v-rows` body (renderVault, lines 1970–1979). */
export function VaultTableBody({ rows, selected, stagger, renderKey, onSelect }: VaultTableProps) {
  if (!rows.length) {
    return (
      <tbody id="v-rows">
        <tr>
          <td colSpan={4} className="v-empty">
            {COPY.vault.empty}
          </td>
        </tr>
      </tbody>
    );
  }
  return (
    <tbody id="v-rows">
      {rows.map((t, i) => (
        <tr
          key={`${t.name}:${renderKey}`}
          data-tool={t.name}
          aria-selected={t.name === selected}
          className={`${t.fresh ? "fresh" : ""}${stagger ? " in" : ""}`}
          style={stagger ? { animationDelay: `${Math.min(i, 14) * 22}ms` } : undefined}
          onClick={() => onSelect(t.name)}
        >
          <td>
            <button
              type="button"
              data-tool-btn={t.name}
              onClick={(e) => {
                e.stopPropagation();
                onSelect(t.name);
                e.currentTarget.focus();
              }}
            >
              <span className={`nm${t.web ? " web" : ""}`}>{t.name}</span>
              <span className="ar">({argNames(t.args)})</span>
            </button>
            {t.fresh ? <span className="newtag">{COPY.vault.newTag}</span> : null}
          </td>
          <td className="num">{t.uses}</td>
          <td className={`num${t.fails ? "" : " zero"}`}>{t.fails}</td>
          <td className="num when">{t.last ? (sameDay(t.last) ? fmtClock(t.last) : fmtShort(t.last)) : COPY.vault.notYet}</td>
        </tr>
      ))}
    </tbody>
  );
}

export const showing = (r: number, n: number): string => fill(COPY.vault.showing, { r, n });

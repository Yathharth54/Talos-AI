import { useEffect } from "react";
import { COPY, fill } from "../../lib/copy";
import { findTool, vaultRows } from "../../store/vaultOps";
import type { UiState, VaultTool } from "../../store/types";
import { VaultDetail } from "./VaultDetail";
import { showing, VaultTableBody } from "./VaultTable";

type Filter = "all" | "web" | "failed";

export interface VaultViewProps {
  tools: VaultTool[];
  filter: Filter;
  query: string;
  selected: string | null;
  stagger: boolean;
  renderKey: number;
  confirmRemove: string | null;
  source: string[] | null;
  /** Demo mode only shows the "source lives at" line. Required so live mode can never fall back to demo copy. */
  demo: boolean;
  onQuery(q: string): void;
  onFilter(f: Filter): void;
  onSelect(name: string): void;
  onFallbackSelect(name: string | null): void;
  onRead(name: string): void;
  onUse(name: string): void;
  onRemove(name: string): void;
  onOpenTool?(name: string): void;
}

/** renderVault's fallback (line 1971): keep the selection if it's in the vault, else the first row, else nothing. */
export function effectiveSelected(tools: VaultTool[], rows: VaultTool[], selected: string | null): string | null {
  if (findTool(tools, selected)) return selected;
  return rows[0] ? rows[0].name : null;
}

const FILTERS: { id: Filter; label: string; count: (t: VaultTool[]) => number }[] = [
  { id: "all", label: COPY.vault.all, count: (t) => t.length },
  { id: "web", label: COPY.vault.web, count: (t) => t.filter((x) => x.web).length },
  { id: "failed", label: COPY.vault.failed, count: (t) => t.filter((x) => x.fails > 0).length },
];

/** The `.vault` grid (static lines 653–677, renderVault 1963–1981). */
export function VaultView(p: VaultViewProps) {
  const rows = vaultRows(p.tools, p.filter as UiState["filter"], p.query);
  const effective = effectiveSelected(p.tools, rows, p.selected);
  const { onFallbackSelect } = p;
  useEffect(() => {
    if (effective !== p.selected) onFallbackSelect(effective);
  }, [effective, p.selected, onFallbackSelect]);
  const all = p.tools.length;
  return (
    <div className="vault">
      <div className="v-main">
        <div>
          <h1>{COPY.vault.title}</h1>
          <p className="lede" id="v-lede">
            {fill(COPY.vault.lede, { n: all })}
          </p>
        </div>
        <div className="v-tools">
          <label htmlFor="v-search" className="sr">
            {COPY.vault.searchLabel}
          </label>
          <input
            id="v-search"
            type="search"
            placeholder={COPY.vault.searchPlaceholder}
            autoComplete="off"
            value={p.query}
            onChange={(e) => p.onQuery(e.target.value)}
          />
          <div className="filters" role="group" aria-label={COPY.vault.filterAria}>
            {FILTERS.map((f) => (
              <button key={f.id} type="button" className="pill ghost" data-filter={f.id} aria-pressed={f.id === p.filter} onClick={() => p.onFilter(f.id)}>
                {f.label} <span className="c" id={`c-${f.id}`}>{f.count(p.tools)}</span>
              </button>
            ))}
          </div>
        </div>
        <div className="tbl-wrap">
          <table className="tbl">
            <thead>
              <tr>
                <th scope="col">{COPY.vault.colTool}</th>
                <th scope="col" className="num">
                  {COPY.vault.colUses}
                </th>
                <th scope="col" className="num">
                  {COPY.vault.colFailures}
                </th>
                <th scope="col" className="num">
                  {COPY.vault.colLast}
                </th>
              </tr>
            </thead>
            <VaultTableBody rows={rows} selected={effective} stagger={p.stagger} renderKey={p.renderKey} onSelect={p.onSelect} />
          </table>
        </div>
        <div className="v-foot">
          <span className="legend">
            <i></i>
            {COPY.vault.legend}
          </span>
          <span id="v-count">{showing(rows.length, all)}</span>
        </div>
      </div>
      <VaultDetail
        tool={findTool(p.tools, effective)}
        source={p.source}
        demo={p.demo}
        confirmRemove={p.confirmRemove}
        onRead={p.onRead}
        onUse={p.onUse}
        onRemove={p.onRemove}
      />
    </div>
  );
}

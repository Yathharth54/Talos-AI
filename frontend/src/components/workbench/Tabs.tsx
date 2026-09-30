import { useRef } from "react";
import { useTabIndicator } from "../../hooks/useTabIndicator";
import { COPY } from "../../lib/copy";
import type { Run, Tab, TabId } from "../../store/types";

/** allTabs() (line 1129): the run log is always the last tab. */
const allTabs = (run: Run): Tab[] => [...(run.tabs || []), { id: "log", label: COPY.bench.tabs.log }];

/** The details tab bar (tabsHtml, lines 1130–1134). */
export function Tabs({ run, onSelect }: { run: Run; onSelect(tab: TabId): void }) {
  const tabs = allTabs(run);
  if (tabs.length < 2) return null;
  return <TabBar run={run} tabs={tabs} onSelect={onSelect} />;
}

function TabBar({ run, tabs, onSelect }: { run: Run; tabs: Tab[]; onSelect(tab: TabId): void }) {
  const ref = useRef<HTMLDivElement>(null);
  useTabIndicator(ref, run.tab, `${run.id}`);
  return (
    <div className="tabs" role="tablist" aria-label={COPY.bench.details} ref={ref}>
      {tabs.map((t) => (
        <button key={t.id} type="button" className="tab" role="tab" data-tab={t.id} aria-selected={String(run.tab === t.id) as "true" | "false"} onClick={() => onSelect(t.id)}>
          {t.label}
          {t.count != null ? (
            <>
              {" "}
              <span className="n">{t.count}</span>
            </>
          ) : null}
        </button>
      ))}
      <span className="tab-ind" aria-hidden="true"></span>
    </div>
  );
}

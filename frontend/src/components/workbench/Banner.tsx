import { useRef } from "react";
import { useScramble } from "../../hooks/useScramble";
import { COPY } from "../../lib/copy";
import { esc } from "../../lib/format";
import type { Banner as BannerData } from "../../store/types";

type BannerProps = { banner: BannerData | null | undefined; onOpenTool?(name: string): void };

function SavedBanner({ name, sub, onOpenTool }: { name: string; sub: string; onOpenTool?(name: string): void }) {
  const ref = useRef<HTMLSpanElement>(null);
  // setBanner() decodes the name when the banner appears (line 1120).
  useScramble(ref, name, 900, { onMount: true });
  return (
    <section className="banner" aria-label={COPY.banner.savedAria}>
      <span className="sq" aria-hidden="true"></span>
      <div className="txt">
        <p>
          <span className="mono gold" data-scramble="" ref={ref} dangerouslySetInnerHTML={{ __html: esc(name) }} />
          {COPY.banner.saved}
        </p>
        <p className="sub">{sub}</p>
      </div>
      <a className="pill ghost sm" href="#vault" data-open-tool={name} onClick={() => onOpenTool?.(name)}>
        {COPY.banner.openInVault}
      </a>
    </section>
  );
}

/** The saved / removed banner (bannerHtml, lines 1122–1128). */
export function Banner({ banner, onOpenTool }: BannerProps) {
  if (!banner) return null;
  if (banner.kind === "saved") return <SavedBanner name={banner.name} sub={banner.sub} onOpenTool={onOpenTool} />;
  return (
    <section className="banner removed" aria-label={COPY.banner.removedAria}>
      <span className="sq" aria-hidden="true"></span>
      <div className="txt">
        <p>
          <span className="mono">{banner.name}</span>
          {COPY.banner.removed}
        </p>
        <p className="sub">{banner.sub}</p>
      </div>
    </section>
  );
}

import { useRef } from "react";
import { useScramble } from "../../hooks/useScramble";
import { COPY } from "../../lib/copy";
import { esc } from "../../lib/format";
import type { Banner as BannerData } from "../../store/types";

type BannerProps = { banner: BannerData | null | undefined; onOpenTool?(name: string): void };

type SavedProps = { name: string; sub: string; animate: boolean; onOpenTool?(name: string): void };

function SavedBanner({ name, sub, animate, onOpenTool }: SavedProps) {
  const ref = useRef<HTMLSpanElement>(null);
  // setBanner() decodes the name when a banner is set (line 1120); renderBench() never does (line 1101).
  useScramble(ref, name, 900, { onMount: animate });
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

const same = (a: BannerData | null | undefined, b: BannerData): boolean => !!a && a.kind === b.kind && a.name === b.name && a.sub === b.sub;

/** The saved / removed banner (bannerHtml, lines 1122–1128). Only a banner set after mount animates. */
export function Banner({ banner, onOpenTool }: BannerProps) {
  const mountBanner = useRef(banner);
  if (!banner) return null;
  if (banner.kind === "saved")
    return <SavedBanner name={banner.name} sub={banner.sub} animate={!same(mountBanner.current, banner)} onOpenTool={onOpenTool} />;
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

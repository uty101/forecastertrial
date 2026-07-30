"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { RegMark } from "@/components/blueprint";
import { SHEETS, TOTAL } from "@/lib/sheets";

/**
 * The drawing-set index, as navigation.
 *
 * Numbered because the sheets are numbered, and in demo order: the live run
 * wins the room, the reasoning trace wins on substance, and the method sheet is
 * what the architecture prize is actually judged on.
 */
export default function Nav() {
  const pathname = usePathname();
  const normalised = pathname.endsWith("/") ? pathname : `${pathname}/`;

  return (
    <header className="border-b border-rule bg-sheet">
      <div className="mx-auto flex max-w-[1640px] flex-wrap items-center gap-x-5 gap-y-2 px-4 py-2.5 sm:px-6">
        <Link href="/" className="flex items-center gap-2.5">
          <RegMark size={17} />
          <span className="display text-[19px] leading-none text-ink">
            forecaster
          </span>
        </Link>
        <p className="tech hidden text-ink-3 md:block">
          an analyst with no incentives
        </p>

        <nav className="ml-auto flex flex-wrap items-center gap-x-1 gap-y-1">
          {SHEETS.map((sheet) => {
            const active =
              sheet.href === "/" ? normalised === "/" : normalised === sheet.href;
            return (
              <Link
                key={sheet.href}
                href={sheet.href}
                className={[
                  "state-change flex items-baseline gap-1.5 border px-2 py-1",
                  active
                    ? "border-accent bg-accent-soft text-accent"
                    : "border-transparent text-ink-2 hover:border-rule",
                ].join(" ")}
              >
                <span className="tech opacity-60">
                  {String(sheet.n).padStart(2, "0")}
                </span>
                <span className="text-[12.5px] font-medium">{sheet.nav}</span>
              </Link>
            );
          })}
          <span className="tech ml-1 text-ink-3">/{TOTAL}</span>
        </nav>
      </div>
    </header>
  );
}

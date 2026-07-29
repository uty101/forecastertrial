"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

/**
 * Four screens plus the model view.
 *
 * Order is the demo order: the live run wins the room, the reasoning trace wins
 * on substance, and the method screen is what the architecture prize is
 * actually judged on.
 */
const ROUTES = [
  { href: "/", label: "Live run" },
  { href: "/forecast/", label: "Forecast" },
  { href: "/reasoning/", label: "Reasoning" },
  { href: "/model/", label: "Model" },
  { href: "/eval/", label: "Method" },
];

export default function Nav() {
  const pathname = usePathname();

  return (
    <header className="border-b border-[--color-line] bg-[--color-surface]">
      <div className="mx-auto flex max-w-[1600px] flex-wrap items-baseline gap-x-6 gap-y-2 px-5 py-3">
        <Link href="/" className="text-[15px] font-semibold tracking-tight">
          forecaster
        </Link>
        <p className="hidden text-[12.5px] text-[--color-ink-3] sm:block">
          an analyst with no incentives
        </p>
        <nav className="ml-auto flex flex-wrap gap-1">
          {ROUTES.map((route) => {
            const active =
              route.href === "/"
                ? pathname === "/"
                : pathname.startsWith(route.href);
            return (
              <Link
                key={route.href}
                href={route.href}
                className={[
                  "state-change rounded-md px-3 py-1.5 text-[13px]",
                  active
                    ? "bg-[--color-accent-soft] font-medium text-[--color-accent]"
                    : "text-[--color-ink-2] hover:bg-[--color-street-soft]",
                ].join(" ")}
              >
                {route.label}
              </Link>
            );
          })}
        </nav>
      </div>
    </header>
  );
}

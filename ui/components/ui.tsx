import type { ReactNode } from "react";

export function Card({
  title,
  hint,
  right,
  children,
  className = "",
}: {
  title?: string;
  hint?: string;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`rounded-xl border border-[--color-line] bg-[--color-surface] ${className}`}
    >
      {(title || right) && (
        <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-[--color-line] px-4 py-3">
          {title && (
            <h2 className="text-[11px] font-bold uppercase tracking-[0.13em] text-[--color-ink-3]">
              {title}
            </h2>
          )}
          {hint && <p className="text-[12.5px] text-[--color-ink-2]">{hint}</p>}
          {right && <div className="ml-auto">{right}</div>}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function Stat({
  label,
  value,
  sub,
  accent = false,
}: {
  label: string;
  value: ReactNode;
  sub?: string;
  accent?: boolean;
}) {
  return (
    <div>
      <p className="text-[11px] font-semibold uppercase tracking-[0.1em] text-[--color-ink-3]">
        {label}
      </p>
      <p
        className={`num mt-1 text-[26px] font-semibold leading-none tracking-tight ${
          accent ? "text-[--color-accent]" : ""
        }`}
      >
        {value}
      </p>
      {sub && <p className="mt-1.5 text-[12px] text-[--color-ink-2]">{sub}</p>}
    </div>
  );
}

/**
 * Empty and error states are designed, not left to chance. Something will be
 * missing on the day, and a screen that says exactly what and why reads as
 * intentional; a blank one reads as broken.
 */
export function Empty({
  title,
  detail,
  command,
}: {
  title: string;
  detail: string;
  command?: string;
}) {
  return (
    <div className="rounded-xl border border-dashed border-[--color-line] bg-[--color-surface] p-8 text-center">
      <p className="text-[14px] font-medium">{title}</p>
      <p className="mx-auto mt-2 max-w-xl text-[13px] text-[--color-ink-2]">
        {detail}
      </p>
      {command && (
        <code className="mt-3 inline-block rounded-md bg-[--color-street-soft] px-3 py-1.5 font-mono text-[12.5px] text-[--color-ink-2]">
          {command}
        </code>
      )}
    </div>
  );
}

/**
 * Shown whenever the loaded run is the synthetic fixture.
 *
 * Non-negotiable: a fabricated result that looks real is precisely what this
 * repo's provenance design exists to prevent, and an unlabelled fixture on a
 * demo machine is how one ends up on a projector. If the trace says synthetic,
 * every screen says synthetic.
 */
export function SyntheticBanner({ trace }: { trace?: Record<string, unknown> }) {
  if (!trace?.["synthetic"]) return null;
  return (
    <div className="rounded-lg border border-amber-400 bg-amber-50 px-4 py-2.5 text-[13px] text-amber-900 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-200">
      <strong>Synthetic fixture — this is not a forecast.</strong>{" "}
      {String(trace["note"] ?? "")}
    </div>
  );
}

export function Pill({
  tone = "neutral",
  children,
}: {
  tone?: "neutral" | "good" | "bad" | "warn" | "accent";
  children: ReactNode;
}) {
  const tones = {
    neutral: "bg-[--color-street-soft] text-[--color-ink-2]",
    good: "bg-[--color-accent-soft] text-[--color-accent]",
    bad: "bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-300",
    warn: "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300",
    accent: "bg-[--color-accent-soft] text-[--color-accent]",
  };
  return (
    <span
      className={`inline-block rounded-full px-2.5 py-0.5 text-[11px] font-semibold ${tones[tone]}`}
    >
      {children}
    </span>
  );
}

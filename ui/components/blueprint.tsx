import type { ReactNode } from "react";

/**
 * The visual grammar of a technical drawing, as components.
 *
 * Rule 4 from globals.css applies to everything here: THE CHROME CARRIES
 * INFORMATION. Registration marks, sheet numbers, coordinate readouts and
 * dimension rules are the language of a drafted sheet, and it would be easy to
 * scatter them as pure ornament. Every one of these takes real props instead —
 * the sheet number is the screen index, the "coordinates" are the ticker and
 * lock date, the dimension rules annotate actual quantities.
 *
 * Decoration that pretends to be data is worse than no decoration, and on a
 * screen whose entire argument is "every number traces to a source" it would be
 * actively self-defeating.
 */

/* ---- registration marks ------------------------------------------------ */

export function RegMark({ size = 16 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      aria-hidden
      className="shrink-0 text-accent"
    >
      <circle cx="8" cy="8" r="4.4" fill="none" stroke="currentColor" strokeWidth="1" />
      <path
        d="M8 0.5V5.2M8 10.8V15.5M0.5 8H5.2M10.8 8H15.5"
        stroke="currentColor"
        strokeWidth="1"
      />
    </svg>
  );
}

/* ---- title block ------------------------------------------------------- */

/**
 * The header strip of a drawing sheet. `readout` is the coordinate slot — it
 * takes the run's own identifiers rather than a decorative lat/long.
 */
export function TitleBlock({
  system,
  readout,
  sheet,
}: {
  system: string;
  readout?: [string, string];
  sheet?: [number, number];
}) {
  return (
    <div className="border-b border-rule">
      <div className="flex flex-wrap items-stretch">
        <div className="flex items-center border-r border-rule px-3 py-2">
          <RegMark />
        </div>
        <dl className="flex flex-1 flex-wrap gap-x-8 gap-y-0.5 px-4 py-2 text-[10.5px]">
          <div className="flex gap-2">
            <dt className="label">project:</dt>
            <dd className="tech font-semibold text-accent">forecaster</dd>
          </div>
          <div className="flex gap-2">
            <dt className="label">system:</dt>
            <dd className="tech text-ink">{system}</dd>
          </div>
          <div className="flex gap-2">
            <dt className="label">version:</dt>
            <dd className="tech text-ink">1.0</dd>
          </div>
        </dl>
        {readout && (
          <div className="flex items-center gap-2 border-l border-rule px-3 py-2">
            <RegMark size={13} />
            <div className="tech text-right leading-tight">
              <div>{readout[0]}</div>
              <div>{readout[1]}</div>
            </div>
          </div>
        )}
      </div>
      {sheet && (
        <div className="flex items-center gap-3 border-t border-dashed border-rule px-4 py-1">
          <span className="flex-1" />
          <span className="tech text-accent">
            {String(sheet[0]).padStart(2, "0")}/{String(sheet[1]).padStart(2, "0")}
          </span>
        </div>
      )}
    </div>
  );
}

/* ---- the sheet --------------------------------------------------------- */

export function Sheet({
  system,
  readout,
  sheet,
  children,
  footer,
}: {
  system: string;
  readout?: [string, string];
  sheet?: [number, number];
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <div className="sheet crop">
      <TitleBlock system={system} readout={readout} sheet={sheet} />
      <div className="px-4 py-5 sm:px-6 sm:py-7">{children}</div>
      {footer}
    </div>
  );
}

/**
 * The bottom strip. In the reference it reads GRID: 8PT / PAPER: ISO A4 — pure
 * print metadata. Here it carries the run's own provenance instead: which
 * prompt versions and which models produced what is on the sheet.
 */
export function SheetFooter({ cells }: { cells: Array<[string, string]> }) {
  return (
    <div className="flex flex-wrap items-stretch border-t border-rule">
      <div className="plate w-10 shrink-0 border-r border-rule" />
      {cells.map(([label, value], i) => (
        <div
          key={label}
          className={`flex-1 px-4 py-2 ${i > 0 ? "border-l border-rule" : ""}`}
        >
          <div className="label">{label}</div>
          <div className="tech mt-0.5 text-ink">{value}</div>
        </div>
      ))}
      <div className="plate w-10 shrink-0 border-l border-rule" />
    </div>
  );
}

/* ---- lede -------------------------------------------------------------- */

/**
 * What this sheet is, in plain sentences.
 *
 * This replaced a 58px two-line headline with a coloured punchline on every
 * sheet — "Tokens are / a budget, not a bill", that sort of thing. Three reasons
 * it had to go, in order of how much they cost:
 *
 * 1. It was a second title. Every sheet already carries its name in the header
 *    block, so the headline restated it in a louder font and bought nothing.
 * 2. It was advertising. This is an instrument someone reads to find out what a
 *    number means, and a slogan above the number is a claim about the work
 *    standing where the work should be.
 * 3. It set the register for everything else. Once the top of the page is
 *    selling, the prose underneath drifts into selling too.
 *
 * So: no headline, no punchline colour, and the explanation that used to be
 * demoted to a caption is now the first thing on the sheet.
 */
export function Lede({ children }: { children: ReactNode }) {
  return (
    <div>
      <div className="h-[2px] w-8 bg-accent" />
      <p className="mt-2.5 max-w-[62ch] text-[12.5px] leading-relaxed text-ink-2">
        {children}
      </p>
    </div>
  );
}

/* ---- status panel ------------------------------------------------------ */

export function Donut({
  fraction,
  tone = "done",
  size = 54,
}: {
  fraction: number;
  tone?: "done" | "running" | "failed" | "idle";
  size?: number;
}) {
  const r = size / 2 - 5;
  const c = 2 * Math.PI * r;
  const clamped = Math.max(0, Math.min(1, fraction));
  const colour = {
    done: "var(--color-structure)",
    running: "var(--color-accent)",
    failed: "var(--color-failed)",
    idle: "var(--color-idle)",
  }[tone];

  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden>
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        fill="none"
        stroke="var(--color-rule)"
        strokeWidth="3.5"
      />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        fill="none"
        stroke={colour}
        strokeWidth="3.5"
        strokeDasharray={`${c * clamped} ${c}`}
        strokeLinecap="butt"
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
        className="state-change"
      />
      {tone === "done" && clamped >= 1 && (
        <path
          d={`M${size / 2 - 6} ${size / 2} l4.5 4.5 L${size / 2 + 6.5} ${size / 2 - 5}`}
          fill="none"
          stroke={colour}
          strokeWidth="2"
          strokeLinecap="round"
        />
      )}
    </svg>
  );
}

export function StatusPanel({
  title,
  state,
  detail,
  fraction,
  tone = "done",
  rows,
}: {
  title: string;
  state: string;
  detail?: string;
  fraction: number;
  tone?: "done" | "running" | "failed" | "idle";
  rows: Array<[string, ReactNode]>;
}) {
  return (
    <div className="border border-rule bg-paper-2">
      <div className="flex items-center justify-between border-b border-rule px-3 py-1.5">
        <span className="label">{title}</span>
        <span className="tech text-ink-3">+</span>
      </div>
      <div className="flex items-center gap-3 px-3 py-3">
        <Donut fraction={fraction} tone={tone} />
        <div>
          <div
            className={`display text-[17px] leading-none ${
              tone === "running"
                ? "text-accent"
                : tone === "failed"
                  ? "text-failed"
                  : "text-structure"
            }`}
          >
            {state}
          </div>
          {detail && <div className="tech mt-1 text-ink-2">{detail}</div>}
        </div>
      </div>
      <dl className="border-t border-rule px-3 py-2">
        {rows.map(([label, value]) => (
          <div
            key={label}
            className="flex items-baseline justify-between gap-4 py-[3px]"
          >
            <dt className="tech text-ink-3">{label}</dt>
            <dd className="num text-[12px] font-semibold text-ink">
              {value}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

/* ---- panels ------------------------------------------------------------ */

export function Panel({
  label,
  hint,
  right,
  children,
  className = "",
  index,
}: {
  label?: string;
  hint?: string;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
  index?: number;
}) {
  return (
    <section className={`border border-rule bg-sheet ${className}`}>
      {(label || right || index !== undefined) && (
        <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-rule px-3 py-1.5">
          {index !== undefined && (
            <span className="tech font-semibold text-accent">
              {String(index).padStart(2, "0")}
            </span>
          )}
          {label && <span className="label">{label}</span>}
          {hint && (
            <span className="text-[11.5px] text-ink-2">{hint}</span>
          )}
          <span className="ml-auto flex items-center gap-2">
            {right}
            <span className="tech text-ink-3">+</span>
          </span>
        </header>
      )}
      <div className="p-3.5">{children}</div>
    </section>
  );
}

/**
 * The bracketed callout from the reference sheets — a short principle pinned to
 * the drawing with a leader line.
 */
export function Callout({
  label,
  children,
  tone = "ink",
}: {
  label: string;
  children: ReactNode;
  tone?: "ink" | "accent" | "structure";
}) {
  const colour = {
    ink: "border-rule",
    accent: "border-accent",
    structure: "border-structure",
  }[tone];
  return (
    <div className={`relative border-l-2 ${colour} bg-paper-2 px-3 py-2.5`}>
      <div className="label">{label}</div>
      <div className="mt-1 text-[12.5px] leading-relaxed text-ink-2">
        {children}
      </div>
    </div>
  );
}

/* ---- stage strip ------------------------------------------------------- */

export interface Stage {
  n: number;
  title: string;
  detail: string;
  state?: "idle" | "running" | "done" | "failed";
}

/** The numbered process cards along the foot of the reference sheets. */
export function StageStrip({ stages }: { stages: Stage[] }) {
  return (
    <div className="scroll-x">
      <div className="flex min-w-[720px] items-stretch">
        {stages.map((stage, i) => {
          const state = stage.state ?? "idle";
          const tint =
            state === "done"
              ? "border-structure bg-structure-soft"
              : state === "running"
                ? "border-accent bg-accent-soft"
                : state === "failed"
                  ? "border-failed bg-accent-soft"
                  : "border-rule bg-sheet";
          return (
            <div key={stage.n} className="flex flex-1 items-center">
              <div
                className={`state-change flex-1 border ${tint} px-3 py-2.5 ${
                  state === "running" ? "node-running" : ""
                }`}
              >
                <div className="tech font-semibold text-accent">
                  {String(stage.n).padStart(2, "0")}
                </div>
                <div className="display mt-1 text-[14px] text-ink">
                  {stage.title}
                </div>
                <div className="mt-1 text-[11px] leading-snug text-ink-2">
                  {stage.detail}
                </div>
              </div>
              {i < stages.length - 1 && (
                <span className="px-1.5 text-ink-3">→</span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ---- dimension rule ---------------------------------------------------- */

/**
 * An annotated measurement. Takes a real quantity — never a paper size — so the
 * most decorative-looking element on the sheet is still saying something.
 */
export function Dimension({
  value,
  label,
  className = "",
}: {
  value: string;
  label?: string;
  className?: string;
}) {
  return (
    <div className={`flex items-center gap-2 ${className}`}>
      <span className="text-ink-3">|←</span>
      <span className="h-px flex-1 bg-rule" />
      <span className="num tech whitespace-nowrap text-ink-2">
        {value}
        {label ? ` ${label}` : ""}
      </span>
      <span className="h-px flex-1 bg-rule" />
      <span className="text-ink-3">→|</span>
    </div>
  );
}

/* ---- small parts ------------------------------------------------------- */

export function Stat({
  label,
  value,
  sub,
  accent = false,
  size = "md",
}: {
  label: string;
  value: ReactNode;
  sub?: string;
  accent?: boolean;
  size?: "md" | "lg";
}) {
  return (
    <div>
      <p className="label">{label}</p>
      <p
        className={`num display mt-1.5 leading-none ${
          size === "lg" ? "text-[clamp(34px,5vw,52px)]" : "text-[26px]"
        } ${accent ? "text-accent" : "text-ink"}`}
      >
        {value}
      </p>
      {sub && (
        <p className="mt-1.5 text-[11.5px] leading-snug text-ink-2">{sub}</p>
      )}
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
    neutral: "border-rule text-ink-2",
    good: "border-structure text-structure",
    bad: "border-failed text-failed",
    warn: "border-accent text-accent",
    accent: "border-accent bg-accent-soft text-accent",
  }[tone];
  return (
    <span
      className={`tech inline-block border px-2 py-[3px] leading-none ${tones}`}
    >
      {children}
    </span>
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
    <div className="border border-dashed border-rule bg-paper-2 p-8 text-center">
      <div className="mx-auto mb-3 w-fit">
        <RegMark size={18} />
      </div>
      <p className="display text-[18px] text-ink">{title}</p>
      <p className="mx-auto mt-2.5 max-w-xl text-[12.5px] leading-relaxed text-ink-2">
        {detail}
      </p>
      {command && (
        <code className="mt-3.5 inline-block border border-rule bg-sheet px-3 py-1.5 font-mono text-[12px] text-ink-2">
          {command}
        </code>
      )}
    </div>
  );
}

/**
 * Shown whenever the loaded run is the synthetic fixture. Non-negotiable: a
 * fabricated result that looks real is precisely what this repo's provenance
 * design exists to prevent, and an unlabelled fixture on a demo machine is how
 * one ends up on a projector.
 */
export function SyntheticBanner({ trace }: { trace?: Record<string, unknown> }) {
  if (!trace?.["synthetic"]) return null;
  return (
    <div className="border-l-2 border-accent bg-accent-soft px-4 py-2.5">
      <div className="label text-accent">⚠ synthetic fixture</div>
      <p className="mt-1 text-[12.5px] leading-relaxed text-ink-2">
        <strong className="text-ink">This is not a forecast.</strong>{" "}
        {String(trace["note"] ?? "")}
      </p>
    </div>
  );
}

/** The disclaimer strip from the reference backtest sheet. Kept because it is
 *  true and because a metrics screen without it is overclaiming. */
export function Disclaimer({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-start gap-2.5 border border-rule bg-paper-2 px-3 py-2">
      <span className="text-[13px] leading-none text-accent">⚠</span>
      <p className="text-[11.5px] leading-relaxed text-ink-2">{children}</p>
    </div>
  );
}

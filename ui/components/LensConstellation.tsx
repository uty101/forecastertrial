"use client";

import type { LensOutput } from "@/lib/types";

/**
 * The seven lenses arranged around the judge — and deliberately NOT connected to
 * each other.
 *
 * This is the diagram that makes the central architectural claim legible. The
 * obvious way to draw a multi-agent system is a mesh: every agent linked to
 * every other, debating. That is the wrong picture here, and drawing it would
 * misrepresent the system.
 *
 * Lenses are blind to each other. Each has one edge, to the judge. The absent
 * peer links are drawn as faint crossed stubs precisely so the absence reads as
 * a decision rather than an omission — because it is the decision the whole
 * ensemble rests on. Lenses that see each other converge, and converging
 * rebuilds consensus, which scores zero.
 *
 * The adversarial step people expect from a mesh happens elsewhere and better:
 * the champion argues each case and then argues against it, before anything is
 * compared.
 */
export default function LensConstellation({
  lenses,
  dropped,
}: {
  lenses: LensOutput[];
  dropped: Record<string, string>;
}) {
  const ALL = [
    "mechanical",
    "guidance",
    "drivers",
    "margins",
    "forensics",
    "peer_read",
    "macro",
  ];
  const byName = Object.fromEntries(lenses.map((l) => [l.lens, l]));

  const cx = 300;
  const cy = 208;
  const r = 148;
  const nodes = ALL.map((name, i) => {
    const angle = (i / ALL.length) * Math.PI * 2 - Math.PI / 2;
    return {
      name,
      x: cx + r * Math.cos(angle),
      y: cy + r * Math.sin(angle),
      lens: byName[name] as LensOutput | undefined,
      isDropped: name in dropped,
    };
  });

  return (
    <div className="scroll-x">
      <svg viewBox="0 0 600 420" className="h-auto w-full min-w-[460px]">
        <defs>
          <marker
            id="toJudge"
            viewBox="0 0 10 10"
            refX="9"
            refY="5"
            markerWidth="5"
            markerHeight="5"
            orient="auto-start-reverse"
          >
            <path d="M0,0 L10,5 L0,10 z" fill="var(--color-structure)" />
          </marker>
        </defs>

        {/* The absent peer links. Faint, crossed, and labelled — the absence is
            the point, so it is drawn rather than left blank. */}
        {nodes.map((a, i) =>
          nodes.slice(i + 1).map((b) => {
            const mx = (a.x + b.x) / 2;
            const my = (a.y + b.y) / 2;
            return (
              <g key={`${a.name}-${b.name}`} opacity="0.16">
                <line
                  x1={a.x}
                  y1={a.y}
                  x2={b.x}
                  y2={b.y}
                  stroke="var(--color-ink-3)"
                  strokeWidth="0.7"
                  strokeDasharray="2 4"
                />
                <path
                  d={`M${mx - 3} ${my - 3} L${mx + 3} ${my + 3} M${mx + 3} ${my - 3} L${mx - 3} ${my + 3}`}
                  stroke="var(--color-failed)"
                  strokeWidth="1"
                />
              </g>
            );
          }),
        )}

        {/* The only real edges: each lens to the judge. */}
        {nodes.map((node) => (
          <line
            key={`edge-${node.name}`}
            x1={node.x}
            y1={node.y}
            x2={cx}
            y2={cy}
            stroke={
              node.isDropped ? "var(--color-failed)" : "var(--color-structure)"
            }
            strokeWidth={node.isDropped ? 0.8 : 1.3}
            strokeDasharray={node.isDropped ? "3 3" : undefined}
            opacity={node.isDropped ? 0.5 : 0.75}
            markerEnd={node.isDropped ? undefined : "url(#toJudge)"}
          />
        ))}

        {/* The judge */}
        <rect
          x={cx - 52}
          y={cy - 30}
          width={104}
          height={60}
          fill="var(--color-accent-soft)"
          stroke="var(--color-accent)"
          strokeWidth="1.6"
        />
        <text
          x={cx}
          y={cy - 8}
          textAnchor="middle"
          className="display fill-accent"
          style={{ fontSize: 15 }}
        >
          JUDGE
        </text>
        <text
          x={cx}
          y={cy + 8}
          textAnchor="middle"
          className="fill-ink-2"
          style={{ fontSize: 8.5 }}
        >
          materiality,
        </text>
        <text
          x={cx}
          y={cy + 19}
          textAnchor="middle"
          className="fill-ink-2"
          style={{ fontSize: 8.5 }}
        >
          never votes
        </text>

        {/* The lenses */}
        {nodes.map((node) => {
          const eps = node.lens?.eps;
          const kept = Boolean(node.lens);
          return (
            <g key={node.name}>
              <circle
                cx={node.x}
                cy={node.y}
                r={40}
                fill={
                  node.isDropped
                    ? "var(--color-paper-2)"
                    : kept
                      ? "var(--color-structure-soft)"
                      : "var(--color-paper-2)"
                }
                stroke={
                  node.isDropped
                    ? "var(--color-failed)"
                    : kept
                      ? "var(--color-structure)"
                      : "var(--color-idle)"
                }
                strokeWidth="1.5"
                strokeDasharray={kept ? undefined : "4 3"}
                className="state-change"
              />
              <text
                x={node.x}
                y={node.y - 4}
                textAnchor="middle"
                className="display fill-ink"
                style={{ fontSize: 10.5 }}
              >
                {node.name.replace("_", " ")}
              </text>
              <text
                x={node.x}
                y={node.y + 10}
                textAnchor="middle"
                className={
                  node.isDropped
                    ? "fill-failed"
                    : "num fill-ink-2"
                }
                style={{ fontSize: 9.5, fontWeight: 600 }}
              >
                {node.isDropped
                  ? "dropped"
                  : eps != null
                    ? `$${eps.toFixed(2)}`
                    : "abstained"}
              </text>
            </g>
          );
        })}

        {/* Legend — where the absence gets named. */}
        <g transform="translate(14, 352)">
          <line
            x1="0"
            y1="6"
            x2="26"
            y2="6"
            stroke="var(--color-structure)"
            strokeWidth="1.3"
          />
          <text x="33" y="9" className="fill-ink-2" style={{ fontSize: 9.5 }}>
            evidence → judge
          </text>

          <g transform="translate(160, 0)">
            <line
              x1="0"
              y1="6"
              x2="26"
              y2="6"
              stroke="var(--color-ink-3)"
              strokeWidth="0.7"
              strokeDasharray="2 4"
              opacity="0.5"
            />
            <path
              d="M10 3 L16 9 M16 3 L10 9"
              stroke="var(--color-failed)"
              strokeWidth="1"
            />
            <text
              x="33"
              y="9"
              className="fill-ink-2"
              style={{ fontSize: 9.5 }}
            >
              no lens-to-lens link — by design
            </text>
          </g>
        </g>
        <text
          x="14"
          y="382"
          className="fill-ink-3"
          style={{ fontSize: 9 }}
        >
          Lenses that see each other converge. Converging rebuilds consensus,
        </text>
        <text
          x="14"
          y="395"
          className="fill-ink-3"
          style={{ fontSize: 9 }}
        >
          which scores zero. The adversarial step is the champion, not a mesh.
        </text>
      </svg>
    </div>
  );
}

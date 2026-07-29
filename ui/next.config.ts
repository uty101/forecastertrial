import type { NextConfig } from "next";

/**
 * Static export. There is no Node server on the day.
 *
 * The pipeline writes out/*.json and out/events.ndjson; this app polls those
 * files. No API between the two processes means nothing to crash mid-demo — no
 * ports, no CORS, no async lifecycle bug at 18:40 — and replay mode comes free,
 * because a recorded run replays through the identical code path.
 */
const nextConfig: NextConfig = {
  output: "export",
  images: { unoptimized: true },
  // Trailing slashes keep `python -m http.server` happy serving the export
  // directly, which is the fallback if `npx serve` misbehaves on venue wifi.
  trailingSlash: true,
};

export default nextConfig;

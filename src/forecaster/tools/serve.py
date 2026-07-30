"""Stage the pipeline's output and serve the UI. One command, no make, no npx.

`make` is not installed on every machine — including, as it turns out, the one
this is being demoed from — so the whole flow needs to work through `uv run`,
which is the one thing guaranteed to be present.

Two things this does that a bare static server does not:

**It refuses to start on an occupied port, and names what is already there.**
The failure this exists to prevent actually happened: another project's Next dev
server was sitting on 3000, so the browser showed a completely different app and
the UI looked broken. A server that silently starts on a different port, or a
browser pointed at someone else's app, wastes far more time than a loud error.

**It stages `out/*.json` into the export before serving.** Next copies `public/`
at build time, so a run that finishes after the build writes files nowhere the
served page can see. Copying into the export directory itself means the served
page and the pipeline share one directory, and a live run streams straight into
the open page.
"""

from __future__ import annotations

import shutil
import socket
import subprocess
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import structlog

log = structlog.get_logger()

# Deliberately not 3000, 3001, 5173 or 8080. Those collide with every other
# front-end project on a developer machine, and a collision here shows up as
# "the UI is broken" rather than as "something else is on that port".
DEFAULT_PORT = 4321

# Everything the sheets and the monitor poll for.
ARTIFACTS = (
    "results.json",
    "events.ndjson",
    "eval.json",
    "agents.json",
    "portfolio.json",
    "build.json",
)


class NoCacheHandler(SimpleHTTPRequestHandler):
    """Serve with caching disabled.

    The page polls `events.ndjson` four times a second while a run is in
    progress. A cached response means the monitor freezes on the first poll and
    looks dead, which is the single most confusing way for this to fail.
    """

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        super().end_headers()

    def log_message(self, fmt: str, *args) -> None:  # noqa: A002
        # Structured logging only; the default writes a line per poll, which at
        # 4 requests a second buries everything else.
        return


def port_owner(port: int) -> str | None:
    """Who is on this port, if anyone. Best-effort and never raises."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.4)
        if probe.connect_ex(("127.0.0.1", port)) != 0:
            return None

    # Something is listening. Try to say what, so the error is actionable.
    try:
        import urllib.request

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1.5) as res:
            body = res.read(4096).decode("utf-8", "replace")
        start = body.find("<title")
        if start != -1:
            title = body[body.find(">", start) + 1 : body.find("</title>", start)]
            return title.strip() or "an unidentified server"
    except Exception:  # noqa: BLE001
        pass
    return "an unidentified server"


def stage(repo: Path, target: Path) -> list[str]:
    """Copy pipeline artifacts next to the served page. Returns what was found."""
    target.mkdir(parents=True, exist_ok=True)
    found = []
    for name in ARTIFACTS:
        source = repo / "out" / name
        if source.exists():
            shutil.copy2(source, target / name)
            found.append(name)
    return found


def build_ui(repo: Path) -> bool:
    """Run the Next static export. Returns False if npm is unavailable."""
    npm = shutil.which("npm")
    if npm is None:
        log.warning("npm_missing", why="cannot build the UI; serving whatever exists")
        return False
    log.info("building_ui")
    result = subprocess.run(  # noqa: S603
        [npm, "run", "build"], cwd=repo / "ui", check=False
    )
    return result.returncode == 0


def serve(
    port: int = DEFAULT_PORT,
    build: bool = True,
    repo: Path | None = None,
) -> None:
    repo = repo or Path(__file__).resolve().parents[3]
    export = repo / "ui" / "out"

    occupant = port_owner(port)
    if occupant is not None:
        raise SystemExit(
            f"\nPort {port} is already serving “{occupant}”.\n\n"
            f"That is not this project. Pick another port:\n"
            f"    uv run forecast ui --port {port + 1}\n\n"
            f"Or stop whatever is on {port} first. Serving on an occupied port is\n"
            f"how you end up staring at a different app and concluding this one is\n"
            f"broken."
        )

    if build:
        build_ui(repo)

    if not (export / "index.html").exists():
        raise SystemExit(
            f"\nNo static export at {export}.\n\n"
            f"Build it first:\n"
            f"    cd ui && npm install && npm run build\n"
            f"then re-run this command with --no-build."
        )

    staged = stage(repo, export)
    if not staged:
        log.warning(
            "no_artifacts",
            why="nothing in out/ to serve — the sheets will show their empty states",
            hint="uv run python -m forecaster.tools.make_fixture --out out",
        )

    handler = partial(NoCacheHandler, directory=str(export))
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)

    print(f"\n  forecaster UI   http://localhost:{port}/")
    print(f"  live monitor    http://localhost:{port}/monitor.html")
    print(f"\n  serving         {export}")
    print(f"  staged          {', '.join(staged) if staged else 'nothing'}")
    print(
        f"\n  For a live run streaming into the open page, point the pipeline at\n"
        f"  the served directory:\n\n"
        f"      FORECASTER_OUT_DIR={export} uv run forecast run "
        f"--ticker NVDA --as-of 2026-08-16\n"
    )
    print("  ctrl-c to stop\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()

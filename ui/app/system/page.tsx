"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

/**
 * `/system/` was a separate sheet drawing the same parts as the live run, with
 * build state painted on instead of live state. The two are merged into `/`,
 * where they are one drawing and an overlay switch.
 *
 * This stays as a redirect rather than being removed, because the URL is in
 * commit messages, in the README's history and quite possibly in a browser tab
 * on the demo machine. A 404 on a link you handed someone is a worse outcome
 * than one file that does nothing but forward.
 *
 * It is a client-side replace, not a push: the static export has no server to
 * issue a 308, and `replace` keeps the dead URL out of the back-button history
 * so leaving the merged screen does not bounce you straight back into it.
 */
export default function SystemRedirect() {
  const router = useRouter();

  useEffect(() => {
    router.replace("/");
  }, [router]);

  return (
    <div className="border border-dashed border-rule px-4 py-6 text-[12px] text-ink-3">
      The system sheet and the live run are one screen now.{" "}
      <a href="/" className="text-accent underline">
        Continue →
      </a>
    </div>
  );
}

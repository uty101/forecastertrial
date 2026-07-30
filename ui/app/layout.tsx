import type { Metadata } from "next";
import Nav from "@/components/Nav";
import "./globals.css";

export const metadata: Metadata = {
  title: "forecaster",
  description:
    "Quarterly EPS forecasting. Seven independent lenses over cited filing evidence, reconciled and judged, then positioned against consensus by a fitted lambda.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className="min-h-screen">
        <Nav />
        {/* Wider and tighter than before: the instrument on / wants the full
            width, and the sheets read better dense than airy now that the
            substrate is dark. Pages own their own internal rhythm. */}
        <main className="mx-auto w-full max-w-[1760px] px-3 py-3">{children}</main>
      </body>
    </html>
  );
}

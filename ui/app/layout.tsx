import type { Metadata } from "next";
import Nav from "@/components/Nav";
import "./globals.css";

export const metadata: Metadata = {
  title: "forecaster — an analyst with no incentives",
  description:
    "An earnings-forecasting agent that knows when to disagree with Wall Street, and more often when not to.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className="min-h-screen">
        <Nav />
        <main className="mx-auto max-w-[1600px] px-5 py-6">{children}</main>
      </body>
    </html>
  );
}

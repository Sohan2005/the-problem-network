import type { Metadata } from "next";
import { Providers } from "./providers";
import "../styles/tokens.css";

export const metadata: Metadata = {
  title: "The Problem Network",
  description: "Translates real-world technical problems into structured, junior-dev-friendly briefs.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}

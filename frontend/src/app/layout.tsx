import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "DB Indoor Navigation",
  description: "Indoor-Navigationsassistent für Deutsche Bahn Bahnhöfe",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="de">
      <body className="antialiased">{children}</body>
    </html>
  );
}

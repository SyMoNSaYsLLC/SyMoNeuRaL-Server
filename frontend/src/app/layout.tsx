import type { Metadata } from "next";
import "@/styles/globals.css";

export const metadata: Metadata = {
  title: {
    default: "SyMoNeuRaL",
    template: "%s — SyMoNeuRaL",
  },
  description:
    "The canonical SyMoNeuRaL frontend. Routes migrate here from the legacy static site one at a time.",
  icons: {
    icon: [
      { url: "/favicon-32.png", sizes: "32x32", type: "image/png" },
      { url: "/favicon-16.png", sizes: "16x16", type: "image/png" },
    ],
  },
};

export const viewport = {
  themeColor: "#0e100f",
};

export default function RootLayout({ children }: { readonly children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

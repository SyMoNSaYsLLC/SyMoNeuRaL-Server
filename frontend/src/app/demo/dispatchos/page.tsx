import type { Metadata } from "next";
import { DispatchWorkspace } from "@/applications/symoneural-dispatchos";

/**
 * The Donnie preview.
 *
 * `noindex, nofollow, noarchive` because this is a named customer's board behind a shared
 * door password, not a public page. Caddy's basicauth already keeps a crawler out, but a
 * robots directive costs nothing and survives the day somebody relaxes the edge rule to show
 * one person one screen.
 */
export const metadata: Metadata = {
  title: "DispatchOS",
  description: "Transport dispatch: booking, quotes, drivers, reminders and review requests.",
  robots: {
    index: false,
    follow: false,
    noarchive: true,
    nocache: true,
    googleBot: { index: false, follow: false, noarchive: true, noimageindex: true },
  },
};

export default function DispatchOsPage() {
  return <DispatchWorkspace />;
}

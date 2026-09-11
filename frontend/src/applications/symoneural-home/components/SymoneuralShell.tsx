import type { ReactNode } from "react";
import { AppShell } from "@/components/shell/AppShell";
import { PRIMARY_NAV } from "@/lib/config";

/**
 * The shared shell, composed.
 *
 * `symoneural-home` owns this because the navigation model is a site-wide concern and must
 * have exactly one owner. An application route renders `<SymoneuralShell>` and supplies only
 * the two strings that describe itself; it never assembles its own navigation, which is how
 * two pages end up disagreeing about what the site contains.
 */

export type SymoneuralShellProps = {
  readonly eyebrow: string;
  readonly title: string;
  readonly headerActions?: ReactNode;
  readonly children: ReactNode;
};

export function SymoneuralShell({
  eyebrow,
  title,
  headerActions,
  children,
}: SymoneuralShellProps) {
  return (
    <AppShell
      nav={PRIMARY_NAV}
      eyebrow={eyebrow}
      title={title}
      {...(headerActions ? { headerActions } : {})}
    >
      {children}
    </AppShell>
  );
}

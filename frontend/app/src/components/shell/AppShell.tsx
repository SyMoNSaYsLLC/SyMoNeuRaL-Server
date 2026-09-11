"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, type ReactNode } from "react";
import { BRAND, type NavItem } from "@/lib/config";
import styles from "./AppShell.module.css";

/**
 * The presentational shell: desktop rail, mobile drawer, application header, workspace.
 *
 * It holds no application knowledge. Which links exist and what the header says are passed
 * in -- `symoneural-home` owns the shared composition, and an application that needs its own
 * header text supplies it. That split is what stops the shell from growing a special case per
 * page, which is how the legacy `site/` collection became entangled in the first place.
 */

export type AppShellProps = {
  readonly nav: readonly NavItem[];
  readonly eyebrow: string;
  readonly title: string;
  readonly headerActions?: ReactNode;
  readonly children: ReactNode;
};

export function AppShell({ nav, eyebrow, title, headerActions, children }: AppShellProps) {
  const pathname = usePathname();
  const [drawerOpen, setDrawerOpen] = useState(false);

  const links = (variant: "rail" | "drawer") =>
    nav.map((item) => {
      const active = pathname === item.href;
      return (
        <li key={item.href}>
          <Link
            href={item.href}
            className={`${styles.navLink} ${active ? styles.navLinkActive : ""}`}
            aria-current={active ? "page" : undefined}
            onClick={variant === "drawer" ? () => setDrawerOpen(false) : undefined}
          >
            {item.label}
          </Link>
        </li>
      );
    });

  return (
    <div className={styles.shell}>
      <aside className={styles.rail}>
        <Link href="/" className={styles.wordmark}>
          SyMoNeu<span>RaL</span>
        </Link>
        <nav aria-label="Primary">
          <ul className={styles.navList}>{links("rail")}</ul>
        </nav>
        <p className={styles.railFoot}>{BRAND.name}</p>
      </aside>

      <div className={styles.main}>
        <header className={styles.header}>
          <button
            type="button"
            className={styles.navToggle}
            aria-expanded={drawerOpen}
            aria-controls="shell-drawer"
            onClick={() => setDrawerOpen((open) => !open)}
          >
            Menu
          </button>
          <div className={styles.headerText}>
            <p className={styles.eyebrow}>{eyebrow}</p>
            <h1 className={styles.title}>{title}</h1>
          </div>
          {headerActions ? <div className={styles.headerActions}>{headerActions}</div> : null}
        </header>

        {drawerOpen ? (
          <div className={styles.drawer} id="shell-drawer">
            <nav aria-label="Primary, phone">
              <ul className={styles.navList}>{links("drawer")}</ul>
            </nav>
          </div>
        ) : null}

        <main className={styles.workspace}>{children}</main>
      </div>
    </div>
  );
}

import Link from "next/link";
import { Panel } from "@/components/ui/Panel";
import { PRIMARY_NAV } from "@/lib/config";
import styles from "../styles/home.module.css";

/**
 * The index page of the NEW frontend, and it says exactly what it is.
 *
 * This is not a replacement for `site/index.html` and must not pretend to be one. The public
 * home page is still the legacy one; this project owns a single migrated route today. Writing
 * a marketing home page here would create a second front door that nobody is serving and that
 * would drift from the real one immediately.
 */
export function MigrationIndex() {
  const migrated = PRIMARY_NAV.filter((item) => item.owner === "next" && item.href !== "/");

  return (
    <>
      <p className={styles.lede}>
        The canonical SyMoNeuRaL frontend. Routes move here one at a time, and a route is only
        listed once it is actually implemented in this project &mdash; everything else is still
        served by the legacy static site.
      </p>

      <div className={styles.grid}>
        <Panel title="Migrated routes" note={`${migrated.length} of 27`}>
          <ul className={styles.list}>
            {migrated.map((item) => (
              <li key={item.href}>
                <Link href={item.href}>{item.label}</Link> &mdash; <code>{item.href}</code>
              </li>
            ))}
          </ul>
        </Panel>

        <Panel title="Still legacy" note="served from site/">
          <p className={styles.status}>
            The remaining 26 pages are unchanged and untouched. The route-ownership map in{" "}
            <code>docs/ops/FRONTEND-ROUTE-OWNERSHIP.md</code> records which application owns
            each one and what it depends on.
          </p>
        </Panel>
      </div>
    </>
  );
}

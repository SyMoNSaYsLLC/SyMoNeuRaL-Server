import type { ReactNode } from "react";
import styles from "./Panel.module.css";

export type PanelProps = {
  readonly title: string;
  /** A short qualifier shown beside the title -- a count, a state, a caveat. */
  readonly note?: string;
  readonly children: ReactNode;
};

export function Panel({ title, note, children }: PanelProps) {
  return (
    <section className={styles.panel}>
      <div className={styles.head}>
        <h2 className={styles.title}>{title}</h2>
        {note ? <p className={styles.note}>{note}</p> : null}
      </div>
      {children}
    </section>
  );
}

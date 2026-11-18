import type { ReactNode } from "react";
import s from "./ui.module.css";

export function Panel({
  title,
  note,
  children,
  id,
}: { title: string; note?: string; children: ReactNode; id?: string }) {
  return (
    <section className={s.panel} aria-labelledby={id}>
      <h2 className={s.panelTitle} id={id}>
        {title}
      </h2>
      {note ? <p className={s.panelNote}>{note}</p> : null}
      {children}
    </section>
  );
}

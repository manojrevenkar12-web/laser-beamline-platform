import s from "./ui.module.css";

export function Skeleton({ height, width = "100%" }: { height: number; width?: string }) {
  return <div className={s.skeleton} style={{ height, width }} aria-hidden="true" />;
}

export function ErrorState({
  what,
  message,
  onRetry,
}: { what: string; message: string; onRetry: () => void }) {
  return (
    <div className={s.state} role="alert">
      <p className={s.stateTitle}>Could not load {what}</p>
      <p className={s.stateText}>
        {message}. The console reads the files that <code>python3 -m evals.console_data</code> writes; check
        they exist, then try again.
      </p>
      <button type="button" className={s.button} onClick={onRetry}>
        Load again
      </button>
    </div>
  );
}

export function EmptyState({ title, text }: { title: string; text: string }) {
  return (
    <div className={s.state}>
      <p className={s.stateTitle}>{title}</p>
      <p className={s.stateText}>{text}</p>
    </div>
  );
}

export function Stat({ value, label }: { value: string; label: string }) {
  return (
    <div className={s.stat}>
      <span className={s.statValue}>{value}</span>
      <span className={s.statLabel}>{label}</span>
    </div>
  );
}

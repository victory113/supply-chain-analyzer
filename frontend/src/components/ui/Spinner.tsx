interface SpinnerProps {
  size?: 'sm' | 'lg';
  label?: string;
}

export function Spinner({ size = 'sm', label }: SpinnerProps) {
  return (
    <span className="row" role="status" aria-live="polite">
      <span className={size === 'lg' ? 'spinner spinner-lg' : 'spinner'} />
      {label ? <span className="small muted">{label}</span> : <span className="sr-only">Loading</span>}
    </span>
  );
}

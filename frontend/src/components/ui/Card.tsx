import type { ReactNode } from 'react';

interface CardProps {
  title?: ReactNode;
  hint?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}

export function Card({ title, hint, action, children, className }: CardProps) {
  return (
    <section className={className ? `card ${className}` : 'card'}>
      {(title || action) && (
        <header className="card-header">
          <div>
            {title && <h2 className="card-title">{title}</h2>}
            {hint && <p className="card-hint">{hint}</p>}
          </div>
          {action}
        </header>
      )}
      {children}
    </section>
  );
}

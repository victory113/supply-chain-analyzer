import { useState } from 'react';
import type { FormEvent } from 'react';
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom';

import { useAuth } from '@/auth/useAuth';
import { ColdStartBanner } from '@/components/ColdStartBanner';
import { Field } from '@/components/ui/Field';
import { InlineError } from '@/components/ui/States';

interface LocationState {
  from?: string;
}

export function LoginPage() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<unknown>(null);
  const [submitting, setSubmitting] = useState(false);

  if (user) return <Navigate to="/" replace />;

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login({ email, password });
      // Return them to whatever they were trying to reach before the redirect.
      const from = (location.state as LocationState | null)?.from;
      navigate(from ?? '/', { replace: true });
    } catch (caught) {
      setError(caught);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="auth-screen">
      <div className="auth-card">
        <h1 className="auth-title">Sign in</h1>
        <p className="auth-subtitle">Analyse your supply chain data.</p>

        <ColdStartBanner />

        <form className="stack" style={{ gap: 14 }} onSubmit={handleSubmit}>
          <Field
            label="Email"
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            autoComplete="email"
            required
            autoFocus
          />
          <Field
            label="Password"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="current-password"
            required
          />

          <InlineError error={error} />

          <button type="submit" className="btn" disabled={submitting}>
            {submitting ? 'Signing in…' : 'Sign in'}
          </button>
        </form>

        <p className="auth-footer">
          No account? <Link to="/register">Create one</Link>
        </p>
      </div>
    </div>
  );
}

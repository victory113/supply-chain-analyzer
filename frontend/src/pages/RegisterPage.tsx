import { useState } from 'react';
import type { FormEvent } from 'react';
import { Link, Navigate, useNavigate } from 'react-router-dom';

import { useAuth } from '@/auth/useAuth';
import { Field } from '@/components/ui/Field';
import { InlineError } from '@/components/ui/States';

/** Mirrors the backend's UserRegister validator so the user isn't told about a
 *  rule only after a round trip. The server still enforces both. */
function validatePassword(password: string): string | null {
  if (password.length < 8) return 'Use at least 8 characters.';
  if (password.length > 72) return 'Passwords are limited to 72 characters.';
  if (/^[a-zA-Z]+$/.test(password) || /^\d+$/.test(password)) {
    return 'Mix letters with numbers or symbols.';
  }
  return null;
}

export function RegisterPage() {
  const { user, register } = useAuth();
  const navigate = useNavigate();

  const [email, setEmail] = useState('');
  const [fullName, setFullName] = useState('');
  const [organization, setOrganization] = useState('');
  const [password, setPassword] = useState('');
  const [touched, setTouched] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [submitting, setSubmitting] = useState(false);

  if (user) return <Navigate to="/" replace />;

  const passwordError = touched ? validatePassword(password) : null;

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setTouched(true);
    if (validatePassword(password)) return;

    setError(null);
    setSubmitting(true);
    try {
      await register({
        email,
        password,
        full_name: fullName || null,
        organization: organization || null,
      });
      navigate('/', { replace: true });
    } catch (caught) {
      setError(caught);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="auth-screen">
      <div className="auth-card">
        <h1 className="auth-title">Create an account</h1>
        <p className="auth-subtitle">Upload a CSV and get a risk read in seconds.</p>

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
            label="Full name"
            value={fullName}
            onChange={(event) => setFullName(event.target.value)}
            autoComplete="name"
            hint="Optional"
          />
          <Field
            label="Organisation"
            value={organization}
            onChange={(event) => setOrganization(event.target.value)}
            autoComplete="organization"
            hint="Optional"
          />
          <Field
            label="Password"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            onBlur={() => setTouched(true)}
            autoComplete="new-password"
            required
            error={passwordError ?? undefined}
            hint="At least 8 characters, mixing letters with numbers or symbols"
          />

          <InlineError error={error} />

          <button type="submit" className="btn" disabled={submitting}>
            {submitting ? 'Creating account…' : 'Create account'}
          </button>
        </form>

        <p className="auth-footer">
          Already have an account? <Link to="/login">Sign in</Link>
        </p>
      </div>
    </div>
  );
}

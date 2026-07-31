import { Navigate, Outlet, useLocation } from 'react-router-dom';

import { Spinner } from '@/components/ui/Spinner';

import { useAuth } from './useAuth';

/**
 * Gate for authenticated routes.
 *
 * Waits for the stored token to be verified before redirecting — otherwise a
 * refresh on a deep link would bounce a signed-in user to the login screen.
 */
export function ProtectedRoute() {
  const { user, initializing } = useAuth();
  const location = useLocation();

  if (initializing) {
    return (
      <div className="auth-screen">
        <Spinner size="lg" label="Restoring your session" />
      </div>
    );
  }

  if (!user) {
    // Remember where they were headed so login can send them back.
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }

  return <Outlet />;
}

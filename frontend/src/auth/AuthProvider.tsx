/** Authentication state: token lifecycle, current user, login/logout. */

import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';

import { ApiError, getToken, setToken, setUnauthorizedHandler } from '@/api/client';
import { authApi } from '@/api/endpoints';
import type { LoginPayload, RegisterPayload, User } from '@/api/types';

import { AuthContext } from './authContext';
import type { AuthState } from './authContext';

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [initializing, setInitializing] = useState(true);

  const logout = useCallback(() => {
    setToken(null);
    setUser(null);
  }, []);

  // A 401 from *any* request means the token is dead — drop the session
  // immediately rather than waiting for the next render to notice.
  useEffect(() => {
    setUnauthorizedHandler(() => setUser(null));
    return () => setUnauthorizedHandler(null);
  }, []);

  // Restore the session on load. A stored token may be expired or revoked, so
  // it is verified against /auth/me before the user is considered signed in.
  useEffect(() => {
    let cancelled = false;

    async function restore() {
      if (!getToken()) {
        if (!cancelled) setInitializing(false);
        return;
      }
      try {
        const me = await authApi.me();
        if (!cancelled) setUser(me);
      } catch (error) {
        if (!(error instanceof ApiError) || error.isAuthError) setToken(null);
      } finally {
        if (!cancelled) setInitializing(false);
      }
    }

    void restore();
    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async (payload: LoginPayload) => {
    const token = await authApi.login(payload);
    setToken(token.access_token);
    setUser(token.user);
  }, []);

  const register = useCallback(async (payload: RegisterPayload) => {
    const token = await authApi.register(payload);
    setToken(token.access_token);
    setUser(token.user);
  }, []);

  const value = useMemo<AuthState>(
    () => ({ user, initializing, login, register, logout }),
    [user, initializing, login, register, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

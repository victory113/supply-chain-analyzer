/**
 * The auth context object and its type.
 *
 * Kept apart from the provider component so that file exports components only
 * — mixing a context export into it breaks React Fast Refresh.
 */

import { createContext } from 'react';

import type { LoginPayload, RegisterPayload, User } from '@/api/types';

export interface AuthState {
  user: User | null;
  /** True until the stored token has been checked against the API. */
  initializing: boolean;
  login: (payload: LoginPayload) => Promise<void>;
  register: (payload: RegisterPayload) => Promise<void>;
  logout: () => void;
}

export const AuthContext = createContext<AuthState | null>(null);

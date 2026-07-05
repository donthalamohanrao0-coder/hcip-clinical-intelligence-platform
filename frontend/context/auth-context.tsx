'use client';

import { createContext, useContext, useEffect, useState, useCallback } from 'react';
import type { AuthSession, User } from '@/lib/types';

const AUTH_KEY = 'hcip_auth';

interface AuthContextValue {
  user:      User | null;
  token:     string | null;
  isLoading: boolean;
  isAdmin:   boolean;
  login:     (email: string, password: string) => Promise<void>;
  logout:    () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [session,   setSession]   = useState<AuthSession | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(AUTH_KEY);
      if (raw) {
        const parsed: AuthSession = JSON.parse(raw);
        if (parsed.expiresAt > Date.now()) {
          setSession(parsed);
        } else {
          localStorage.removeItem(AUTH_KEY);
        }
      }
    } catch { /* ignore */ }
    setIsLoading(false);
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const resp = await fetch('/api/auth/login', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ email, password }),
    });

    if (!resp.ok) {
      const err = await resp.json();
      throw new Error(err.error || 'Login failed');
    }

    const data = await resp.json();
    const newSession: AuthSession = {
      user:      data.user,
      token:     data.token,
      expiresAt: Date.now() + 8 * 60 * 60 * 1000, // 8 hours
    };

    localStorage.setItem(AUTH_KEY, JSON.stringify(newSession));

    // Set a cookie so middleware can read the role for server-side protection
    document.cookie = `hcip_auth_role=${data.user.role}; path=/; max-age=${8 * 60 * 60}; SameSite=Lax`;

    setSession(newSession);
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem(AUTH_KEY);
    // Clear the role cookie
    document.cookie = 'hcip_auth_role=; path=/; max-age=0';
    setSession(null);
    window.location.href = '/login';
  }, []);

  return (
    <AuthContext.Provider value={{
      user:    session?.user ?? null,
      token:   session?.token ?? null,
      isLoading,
      isAdmin: session?.user.role === 'admin',
      login,
      logout,
    }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be inside AuthProvider');
  return ctx;
}

import { useState } from 'react';
import { HCIPApiError } from '@/lib/api';
import { saveToHistory } from '@/lib/history';
import type { QueryResult } from '@/lib/types';

interface UseClinicalQueryReturn {
  result:    QueryResult | null;
  isLoading: boolean;
  error:     string | null;
  submit:    (query: string, kbId: string, orgId?: string) => Promise<void>;
  reset:     () => void;
}

export function useClinicalQuery(organizationId?: string): UseClinicalQueryReturn {
  const [result,    setResult]    = useState<QueryResult | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error,     setError]     = useState<string | null>(null);

  const submit = async (query: string, kbId: string, orgId?: string) => {
    setIsLoading(true);
    setError(null);
    setResult(null);

    // Read auth token from localStorage (set by auth-context)
    let token = '';
    try {
      const raw = localStorage.getItem('hcip_auth');
      if (raw) {
        const session = JSON.parse(raw);
        token = session.token ?? '';
      }
    } catch { /* ignore */ }

    try {
      const res = await fetch('/api/query', {
        method:  'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { 'X-API-Token': token } : {}),
        },
        body: JSON.stringify({
          query,
          knowledge_base_id: kbId,
          organization_id:   orgId ?? organizationId,
        }),
      });

      const json = await res.json();

      if (!res.ok || json.success === false) {
        throw new HCIPApiError(
          json.error ?? 'Request failed',
          res.status,
          json.detail,
        );
      }

      const data: QueryResult = json.data ?? json;
      setResult(data);
      saveToHistory(query, data);
    } catch (err) {
      if (err instanceof HCIPApiError) {
        setError(`${err.message}${err.detail ? `: ${err.detail}` : ''}`);
      } else {
        setError('An unexpected error occurred. Please try again.');
      }
    } finally {
      setIsLoading(false);
    }
  };

  const reset = () => {
    setResult(null);
    setError(null);
  };

  return { result, isLoading, error, submit, reset };
}

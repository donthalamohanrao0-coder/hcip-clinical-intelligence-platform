'use client';

import { useState, useRef, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/context/auth-context';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Alert, AlertDescription } from '@/components/ui/alert';
import {
  AlertCircle,
  Heart,
  Shield,
  Stethoscope,
  Brain,
  FileSearch,
  Loader2,
  CheckCircle2,
} from 'lucide-react';

const FEATURES = [
  { icon: Brain,       text: 'Clinical AI with evidence-based reasoning'          },
  { icon: Stethoscope, text: 'Evidence-based answers with full citation trails'   },
  { icon: FileSearch,  text: 'Intelligent search across your clinical libraries'  },
  { icon: Shield,      text: 'HIPAA-compliant with role-based access control'     },
];

export default function LoginPage() {
  const router      = useRouter();
  const { login, user, isLoading: authLoading } = useAuth();

  // Already logged in — redirect immediately
  useEffect(() => {
    if (!authLoading && user) {
      router.replace('/dashboard');
    }
  }, [authLoading, user, router]);

  const emailRef    = useRef<HTMLInputElement>(null);
  const passwordRef = useRef<HTMLInputElement>(null);

  const [email,     setEmail]     = useState('');
  const [password,  setPassword]  = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error,     setError]     = useState<string | null>(null);
  const [success,   setSuccess]   = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email || !password) {
      setError('Please enter your email and password.');
      return;
    }
    setIsLoading(true);
    setError(null);

    try {
      await login(email, password);
      setSuccess(true);
      setTimeout(() => router.replace('/dashboard'), 600);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed. Please try again.');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-blue-950 via-blue-900 to-slate-900 p-4">
      {/* Background grid pattern */}
      <div className="absolute inset-0 opacity-5" style={{
        backgroundImage: 'linear-gradient(rgba(255,255,255,.1) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.1) 1px, transparent 1px)',
        backgroundSize: '40px 40px',
      }} />

      <div className="relative w-full max-w-5xl">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-0 rounded-2xl overflow-hidden shadow-2xl border border-white/10">

          {/* Left panel — branding */}
          <div className="hidden lg:flex flex-col justify-between bg-gradient-to-b from-blue-800/80 to-blue-900/90 backdrop-blur-sm p-10 border-r border-white/10">
            {/* Logo */}
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-white/10 border border-white/20">
                <Heart className="h-5 w-5 text-white" />
              </div>
              <div>
                <p className="text-xl font-bold text-white tracking-tight">HCIP</p>
                <p className="text-xs text-blue-300">Clinical Intelligence Platform</p>
              </div>
            </div>

            {/* Tagline */}
            <div className="space-y-4">
              <h1 className="text-3xl font-bold text-white leading-tight">
                Evidence-based clinical decisions, powered by AI.
              </h1>
              <p className="text-blue-200 text-sm leading-relaxed">
                The enterprise-grade RAG platform purpose-built for healthcare professionals.
                Accurate, cited, and HIPAA-compliant.
              </p>
            </div>

            {/* Feature list */}
            <div className="space-y-3">
              {FEATURES.map(({ icon: Icon, text }) => (
                <div key={text} className="flex items-start gap-3">
                  <div className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-lg bg-white/10">
                    <Icon className="h-3.5 w-3.5 text-blue-200" />
                  </div>
                  <p className="text-sm text-blue-100 leading-snug">{text}</p>
                </div>
              ))}
            </div>

            {/* Badges */}
            <div className="flex flex-wrap gap-2">
              <span className="inline-flex items-center gap-1.5 rounded-full border border-green-400/30 bg-green-400/10 px-3 py-1 text-xs text-green-300">
                <Shield className="h-3 w-3" />
                HIPAA Compliant
              </span>
              <span className="inline-flex items-center gap-1.5 rounded-full border border-blue-400/30 bg-blue-400/10 px-3 py-1 text-xs text-blue-300">
                <Brain className="h-3 w-3" />
                Powered by Clinical AI
              </span>
            </div>
          </div>

          {/* Right panel — login form */}
          <div className="flex flex-col justify-center bg-white dark:bg-slate-950 p-8 lg:p-10">
            {/* Mobile logo */}
            <div className="flex items-center gap-2 mb-8 lg:hidden">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary">
                <Heart className="h-4 w-4 text-white" />
              </div>
              <p className="text-base font-bold tracking-tight">HCIP</p>
            </div>

            <div className="space-y-1 mb-8">
              <h2 className="text-2xl font-bold text-foreground">Sign in to HCIP</h2>
              <p className="text-sm text-muted-foreground">For licensed healthcare professionals only</p>
            </div>

            {/* Error */}
            {error && (
              <Alert variant="destructive" className="mb-5">
                <AlertCircle className="h-4 w-4" />
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}

            {/* Success */}
            {success && (
              <Alert className="mb-5 border-green-200 bg-green-50 text-green-800">
                <CheckCircle2 className="h-4 w-4 text-green-600" />
                <AlertDescription>Signed in successfully. Redirecting...</AlertDescription>
              </Alert>
            )}

            <form onSubmit={handleSubmit} className="space-y-5">
              <div className="space-y-2">
                <Label htmlFor="email">Email address</Label>
                <Input
                  id="email"
                  ref={emailRef}
                  type="email"
                  placeholder="you@hospital.org"
                  value={email}
                  onChange={e => setEmail(e.target.value)}
                  autoComplete="email"
                  disabled={isLoading}
                  required
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="password">Password</Label>
                <Input
                  id="password"
                  ref={passwordRef}
                  type="password"
                  placeholder="••••••••••••"
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                  autoComplete="current-password"
                  disabled={isLoading}
                  required
                />
              </div>

              <Button
                type="submit"
                className="w-full"
                size="lg"
                disabled={isLoading || success}
              >
                {isLoading ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Signing in...
                  </>
                ) : success ? (
                  <>
                    <CheckCircle2 className="h-4 w-4" />
                    Signed in
                  </>
                ) : (
                  'Sign In'
                )}
              </Button>
            </form>

            {/* Footer */}
            <p className="mt-8 text-center text-[11px] text-muted-foreground">
              For authorized clinical staff only.{' '}
              <span className="text-primary">HIPAA</span> compliant.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

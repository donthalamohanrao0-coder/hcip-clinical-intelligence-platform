import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

const PUBLIC_PATHS = ['/login', '/api/auth'];

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Always allow public paths
  if (PUBLIC_PATHS.some(p => pathname.startsWith(p))) {
    return NextResponse.next();
  }

  // Allow static assets and Next internals
  if (
    pathname.startsWith('/_next') ||
    pathname.startsWith('/favicon') ||
    pathname.includes('.')
  ) {
    return NextResponse.next();
  }

  // Check auth cookie (set on login via document.cookie)
  const auth = request.cookies.get('hcip_auth_role');

  // Redirect unauthenticated users to login (non-API routes only)
  if (!auth && !pathname.startsWith('/api')) {
    return NextResponse.redirect(new URL('/login', request.url));
  }

  // Admin-only routes
  if (pathname.startsWith('/admin') && auth?.value !== 'admin') {
    return NextResponse.redirect(new URL('/dashboard', request.url));
  }

  // Pass the role along as a header for API routes
  const response = NextResponse.next();
  if (auth) {
    response.headers.set('x-user-role', auth.value);
  }

  return response;
}

export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'],
};

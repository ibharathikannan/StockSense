import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// Runs before every page request (Next.js 16 renamed `middleware` to `proxy`).
// It only checks that a session cookie *exists* and bounces anonymous visitors
// to /login. The token itself is verified by FastAPI on every API call, and the
// client re-checks with GET /api/auth/me — so this is a UX gate, not the
// security boundary.
const COOKIE_NAME = process.env.AUTH_COOKIE_NAME ?? "access_token";

export function proxy(request: NextRequest) {
  if (request.cookies.has(COOKIE_NAME)) return NextResponse.next();

  const loginUrl = new URL("/login", request.url);
  const { pathname, search } = request.nextUrl;
  if (pathname !== "/") loginUrl.searchParams.set("next", pathname + search);
  return NextResponse.redirect(loginUrl);
}

export const config = {
  // Everything except the API proxy, Next internals, static files, /login and /register.
  matcher: ["/((?!api|_next/static|_next/image|icon.svg|login|register).*)"],
};

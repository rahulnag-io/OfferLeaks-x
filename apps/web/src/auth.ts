/**
 * Auth.js (NextAuth) configuration.
 *
 * This is the frontend's own login/session orchestration -- Google OAuth
 * and the credentials form. It is NOT what the backend trusts. On every
 * successful sign-in (credentials or Google), the backend's own
 * access/refresh JWT pair is fetched and stashed inside NextAuth's session
 * token (already httpOnly + encrypted at rest -- see architecture.md
 * §0.11 "httpOnly cookies, not localStorage"). The `jwt` callback also
 * rotates that pair via `/auth/refresh` before it expires. The backend
 * never has to know or care that NextAuth exists; it just verifies
 * whatever access token shows up in an `Authorization` header.
 */

import NextAuth from "next-auth";
import Credentials from "next-auth/providers/credentials";
import Google from "next-auth/providers/google";

import { googleOauthUpsert, loginUser, logoutUser, refreshTokens } from "@/lib/auth/backend-client";

// Refresh the access token slightly before it actually expires, so a
// request that starts just under the wire doesn't race the expiry.
const ACCESS_TOKEN_REFRESH_SKEW_MS = 60_000;

export const { handlers, auth, signIn, signOut } = NextAuth({
  session: { strategy: "jwt" },
  pages: { signIn: "/login" },
  providers: [
    Google,
    Credentials({
      credentials: {
        email: { label: "Email", type: "email" },
        password: { label: "Password", type: "password" },
      },
      async authorize(credentials) {
        const email = typeof credentials?.email === "string" ? credentials.email : null;
        const password = typeof credentials?.password === "string" ? credentials.password : null;
        if (!email || !password) return null;

        const result = await loginUser(email, password);
        if (!result) return null;

        return {
          id: result.user.id,
          email: result.user.email,
          name: result.user.full_name,
          role: result.user.role,
          accessToken: result.access_token,
          accessTokenExpiresAt: result.access_token_expires_at,
          refreshToken: result.refresh_token,
        };
      },
    }),
  ],
  callbacks: {
    async jwt({ token, user, account, profile }) {
      // Initial credentials sign-in: `authorize()` already talked to the
      // backend and attached its tokens to `user`.
      if (user && account?.provider === "credentials") {
        return {
          ...token,
          sub: user.id,
          role: user.role,
          accessToken: user.accessToken,
          accessTokenExpiresAt: user.accessTokenExpiresAt,
          refreshToken: user.refreshToken,
          error: undefined,
        };
      }

      // Initial Google sign-in: exchange the verified Google identity for
      // the backend's own tokens via the internal-secret-gated upsert.
      if (account?.provider === "google" && profile?.sub && profile.email) {
        const result = await googleOauthUpsert(
          profile.sub,
          profile.email,
          typeof profile.name === "string" ? profile.name : null,
        );
        if (!result) {
          return { ...token, error: "OAuthUpsertError" };
        }
        return {
          ...token,
          sub: result.user.id,
          role: result.user.role,
          accessToken: result.access_token,
          accessTokenExpiresAt: result.access_token_expires_at,
          refreshToken: result.refresh_token,
          error: undefined,
        };
      }

      // Subsequent requests on an existing session: still fresh, no-op.
      if (
        token.accessTokenExpiresAt &&
        Date.now() < new Date(token.accessTokenExpiresAt).getTime() - ACCESS_TOKEN_REFRESH_SKEW_MS
      ) {
        return token;
      }

      // Expiring/expired: rotate via the refresh token.
      if (!token.refreshToken) {
        return token;
      }
      const refreshed = await refreshTokens(token.refreshToken);
      if (!refreshed) {
        return { ...token, error: "RefreshTokenExpiredError" };
      }

      return {
        ...token,
        role: refreshed.user.role,
        accessToken: refreshed.access_token,
        accessTokenExpiresAt: refreshed.access_token_expires_at,
        refreshToken: refreshed.refresh_token,
        error: undefined,
      };
    },

    async session({ session, token }) {
      if (token.sub) session.user.id = token.sub;
      if (token.role) session.user.role = token.role;
      session.accessToken = token.accessToken;
      session.error = token.error;
      return session;
    },

    authorized({ auth: session, request }) {
      const isProtected = request.nextUrl.pathname.startsWith("/dashboard");
      if (isProtected) return Boolean(session?.user) && !session?.error;
      return true;
    },
  },
  events: {
    // Server-side only (never sent to the browser): revoke the backend
    // refresh token on sign-out, in addition to NextAuth discarding its
    // own session cookie.
    async signOut(message) {
      const refreshToken = "token" in message ? message.token?.refreshToken : undefined;
      if (refreshToken) await logoutUser(refreshToken);
    },
  },
});

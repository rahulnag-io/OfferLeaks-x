import type { Role } from "@offerleaks/shared-types";
import type { DefaultSession } from "next-auth";

/**
 * The refresh token deliberately does NOT appear on `Session` -- anything
 * on `Session` is serialized to the browser for `useSession()`. It only
 * ever lives inside the encrypted JWT session cookie, read server-side via
 * the `jwt` callback and the `signOut` event (see auth.ts).
 */
declare module "next-auth" {
  interface User {
    role?: Role;
    accessToken?: string;
    accessTokenExpiresAt?: string;
    refreshToken?: string;
  }

  interface Session {
    user: {
      id: string;
      role: Role;
    } & DefaultSession["user"];
    accessToken?: string;
    error?: "RefreshTokenExpiredError" | "OAuthUpsertError";
  }
}

declare module "@auth/core/jwt" {
  interface JWT {
    role?: Role;
    accessToken?: string;
    accessTokenExpiresAt?: string;
    refreshToken?: string;
    error?: "RefreshTokenExpiredError" | "OAuthUpsertError";
  }
}

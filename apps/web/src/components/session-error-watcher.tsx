"use client";

import { signOut, useSession } from "next-auth/react";
import { useEffect } from "react";

/**
 * If the `jwt` callback couldn't refresh the backend's access token (it
 * expired, was revoked, or the refresh call failed), the session carries
 * an `error` flag. Silently keeping that session around would mean every
 * subsequent API call fails with 401 -- so once the error is visible on
 * the client, immediately clear the (now-useless) session.
 */
export function SessionErrorWatcher() {
  const { data: session } = useSession();

  useEffect(() => {
    if (session?.error) {
      void signOut({ redirectTo: "/login" });
    }
  }, [session?.error]);

  return null;
}

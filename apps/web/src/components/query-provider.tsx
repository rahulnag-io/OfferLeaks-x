"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import type { ReactNode } from "react";

export function QueryProvider({ children }: { children: ReactNode }) {
  // One QueryClient per component-tree mount (not module scope): avoids
  // sharing cached data across different users/requests on the server,
  // and avoids recreating it on every render on the client.
  const [queryClient] = useState(() => new QueryClient());

  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

import { redirect } from "next/navigation";

import { auth } from "@/auth";
import { AppShell } from "@/components/layout/app-shell";
import { getCurrentUser } from "@/lib/api";
import { SignOutButton } from "@/app/dashboard/sign-out-button";

export default async function DashboardLayout({ children }: { children: React.ReactNode }) {
  const session = await auth();
  if (!session?.user || !session.accessToken) {
    redirect("/login");
  }

  // Same round-trip the dashboard has always made: the backend
  // independently verifies the access token and is the only source for
  // the identity shown in the nav.
  const user = await getCurrentUser(session.accessToken);

  return (
    <AppShell userLabel={user.full_name ?? user.email} signOutSlot={<SignOutButton />}>
      {children}
    </AppShell>
  );
}

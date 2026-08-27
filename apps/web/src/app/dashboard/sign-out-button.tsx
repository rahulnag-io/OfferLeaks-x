"use client";

import { signOut } from "next-auth/react";
import { LogOut } from "lucide-react";

import { Button } from "@/components/ui/button";

export function SignOutButton() {
  return (
    <Button variant="outline" size="sm" onClick={() => signOut({ redirectTo: "/" })}>
      <LogOut className="h-3.5 w-3.5" />
      Sign out
    </Button>
  );
}

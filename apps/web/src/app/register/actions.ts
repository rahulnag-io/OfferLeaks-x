"use server";

import { signIn } from "@/auth";
import { EmailAlreadyRegisteredError, registerUser } from "@/lib/auth/backend-client";
import { registerSchema } from "@/lib/auth/schemas";

export type RegisterResult = { success: true } | { success: false; error: string };

export async function registerAction(input: {
  email: string;
  password: string;
  fullName?: string;
}): Promise<RegisterResult> {
  const parsed = registerSchema.safeParse(input);
  if (!parsed.success) {
    return { success: false, error: parsed.error.issues[0]?.message ?? "Invalid input" };
  }

  try {
    await registerUser(parsed.data.email, parsed.data.password, parsed.data.fullName ?? null);
  } catch (err) {
    if (err instanceof EmailAlreadyRegisteredError) {
      return { success: false, error: err.message };
    }
    return { success: false, error: "Something went wrong. Please try again." };
  }

  // Registration succeeded; establish a NextAuth session the same way a
  // normal credentials login would, so the person lands signed in.
  try {
    await signIn("credentials", {
      email: parsed.data.email,
      password: parsed.data.password,
      redirect: false,
    });
  } catch {
    // The account exists even if this auto-login step fails -- the person
    // can still sign in manually from /login.
  }

  return { success: true };
}

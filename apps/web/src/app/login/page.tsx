import { LoginForm } from "@/app/login/login-form";
import { AuthShell } from "@/components/auth/auth-shell";

export default function LoginPage() {
  return (
    <AuthShell title="Sign in" description="Welcome back to OfferLeaks.">
      <LoginForm />
    </AuthShell>
  );
}

import { RegisterForm } from "@/app/register/register-form";
import { AuthShell } from "@/components/auth/auth-shell";

export default function RegisterPage() {
  return (
    <AuthShell title="Create your account" description="Start checking offers before you act on them.">
      <RegisterForm />
    </AuthShell>
  );
}

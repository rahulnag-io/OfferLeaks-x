import { redirect } from "next/navigation";

import { auth } from "@/auth";
import { AnalysisUploader } from "@/app/dashboard/upload/analysis-uploader";
import { PageHeader } from "@/components/layout/page-header";

export default async function UploadPage() {
  const session = await auth();
  if (!session?.user) {
    redirect("/login");
  }

  return (
    <div className="mx-auto max-w-2xl">
      <PageHeader
        title="Scan an offer letter"
        description="Upload a PDF, JPEG, or PNG of the offer letter. We'll read it and tell you what we find — red flags, a risk score, and our reasoning."
      />

      {/* Client Component: never receives the backend access token -- it
          talks to this app's own /api/analyses route, which attaches the
          token server-side (see app/api/analyses/route.ts). */}
      <AnalysisUploader />
    </div>
  );
}

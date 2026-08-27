"use client";

import { useId, useRef, useState } from "react";
import { UploadCloud } from "lucide-react";

import { FilePreview } from "@/components/analysis/file-preview";
import { cn } from "@/lib/utils";

const ACCEPTED_TYPES = "application/pdf,image/jpeg,image/png";
const ACCEPTED_LABEL = "PDF, JPEG, or PNG";

export function UploadDropzone({
  file,
  onFileChange,
  disabled,
}: {
  file: File | null;
  onFileChange: (file: File | null) => void;
  disabled?: boolean;
}) {
  const inputId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [isDragging, setIsDragging] = useState(false);

  function handleFiles(fileList: FileList | null) {
    const next = fileList?.[0];
    if (next) onFileChange(next);
  }

  if (file) {
    return (
      <FilePreview
        file={file}
        disabled={disabled}
        onRemove={() => {
          onFileChange(null);
          if (inputRef.current) inputRef.current.value = "";
        }}
      />
    );
  }

  return (
    <div>
      <label
        htmlFor={inputId}
        onDragOver={(e) => {
          e.preventDefault();
          if (!disabled) setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setIsDragging(false);
          if (!disabled) handleFiles(e.dataTransfer.files);
        }}
        className={cn(
          "flex cursor-pointer flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed px-6 py-12 text-center transition-colors",
          disabled && "pointer-events-none opacity-60",
          isDragging ? "border-primary bg-primary-50" : "border-border bg-secondary/40 hover:border-primary/50 hover:bg-primary-50/60",
        )}
      >
        <div className="flex h-12 w-12 items-center justify-center rounded-full bg-primary-100 text-primary-700">
          <UploadCloud className="h-6 w-6" strokeWidth={1.75} />
        </div>
        <div>
          <p className="text-sm font-medium text-foreground">
            <span className="text-primary underline underline-offset-2">Choose a file</span> or drag it here
          </p>
          <p className="mt-1 text-xs text-muted-foreground">{ACCEPTED_LABEL}</p>
        </div>
        <input
          ref={inputRef}
          id={inputId}
          type="file"
          accept={ACCEPTED_TYPES}
          disabled={disabled}
          onChange={(e) => handleFiles(e.target.files)}
          className="sr-only"
        />
      </label>
    </div>
  );
}

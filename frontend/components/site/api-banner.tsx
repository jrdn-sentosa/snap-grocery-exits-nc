"use client";

import { AlertTriangle, Loader2 } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";

/** Shown while the first call is slow (Modal cold start). */
export function WakingNotice() {
  return (
    <div role="status" className="flex items-center gap-2 border border-rule bg-paper-light px-3 py-2 text-sm text-ink-2">
      <Loader2 className="size-4 animate-spin" aria-hidden />
      Waking up the scoring service… the first request after a quiet period can take up to 45 seconds.
    </div>
  );
}

const COPY: Record<string, { title: string; body: string }> = {
  network: { title: "The scoring service is unreachable", body: "Check your connection and try again. The store list below still works; risk scores are missing until the service answers." },
  timeout: { title: "The scoring service is taking too long", body: "It did not answer within 45 seconds. It may be starting up. Try again." },
  unavailable: { title: "The scoring service is not ready", body: "It is starting up or failed its self-check, so it is refusing to score. Try again in a minute." },
  server: { title: "The scoring service had an error", body: "Something went wrong on the server. Try again; if it keeps happening, the service may be down." },
  unexpected: { title: "Unexpected answer from the scoring service", body: "The response was not what the site expects. Try again." },
  validation: { title: "The scoring service refused the request", body: "One or more inputs are not valid." },
};

/** Error banner with a retry button. Pass the error from useScores()/useModelInfo(). */
export function ApiErrorBanner({ error, onRetry, retrying }: { error: Error; onRetry?: () => void; retrying?: boolean }) {
  const kind = error instanceof ApiError ? error.kind : "unexpected";
  const copy = COPY[kind] ?? COPY.unexpected;
  const problems = error instanceof ApiError ? error.problems : [];
  return (
    <Alert role="alert" className="border-tomato bg-paper-light">
      <AlertTriangle className="text-tomato" aria-hidden />
      <AlertTitle className="font-medium">{copy.title}</AlertTitle>
      <AlertDescription>
        <p>{copy.body}</p>
        {problems.length > 0 && (
          <details className="mt-2 text-xs">
            <summary className="cursor-pointer">Details from the service</summary>
            <ul className="mt-1 list-disc pl-5">
              {problems.map((p) => (
                <li key={p} className="break-words">{p}</li>
              ))}
            </ul>
          </details>
        )}
        {onRetry && (
          <Button type="button" variant="outline" size="sm" className="mt-3" onClick={onRetry} disabled={retrying}>
            {retrying ? "Trying…" : "Try again"}
          </Button>
        )}
      </AlertDescription>
    </Alert>
  );
}

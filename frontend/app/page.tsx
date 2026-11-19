"use client";

import { ApiErrorBanner, WakingNotice } from "@/components/site/api-banner";
import { Skeleton } from "@/components/ui/skeleton";
import { useModelInfo, useScores, useStores } from "@/lib/data";

// Temporary home: proves the live data path (static JSON + batched POST /predict + /model-info) end to end.
// The store map replaces this next.
export default function Home() {
  const stores = useStores();
  const scores = useScores();
  const info = useModelInfo();
  const tiers = { high: 0, medium: 0, low: 0 };
  scores.data?.forEach((p) => (tiers[p.tier] += 1));
  return (
    <div className="mx-auto max-w-[1440px] space-y-6 px-5 py-10">
      <h1 className="font-serif text-5xl">
        Which grocery stores <em className="text-tomato">will lose SNAP?</em>
      </h1>
      {(scores.slow || info.slow) && <WakingNotice />}
      {scores.error && <ApiErrorBanner error={scores.error} onRetry={scores.retry} retrying={scores.status === "loading"} />}
      <dl className="grid max-w-xl grid-cols-2 gap-3 font-mono text-sm">
        <dt>Stores (static data)</dt>
        <dd>{stores.data ? stores.data.length : <Skeleton className="h-4 w-12" />}</dd>
        <dt>Scored by the API</dt>
        <dd>{scores.data ? scores.data.size : <Skeleton className="h-4 w-12" />}</dd>
        <dt>High / medium / low</dt>
        <dd>{scores.data ? `${tiers.high} / ${tiers.medium} / ${tiers.low}` : <Skeleton className="h-4 w-24" />}</dd>
        <dt>Tier cutoffs</dt>
        <dd>{info.data ? `${info.data.metadata.tier_cutoffs.low} / ${info.data.metadata.tier_cutoffs.high}` : <Skeleton className="h-4 w-24" />}</dd>
      </dl>
    </div>
  );
}

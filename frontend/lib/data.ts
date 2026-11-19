"use client";

import { getModelInfo, predict } from "./api";
import { createResource, useResource } from "./resource";
import type { Meta, ModelInfo, Prediction, Store, StoresFile, TractsFile } from "./types";

async function json<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`Could not load ${path} (${res.status})`);
  return (await res.json()) as T;
}

// Static site data (public/data, written by src/site/01_export_site_data.py). Same origin, so no CORS and no cold start.
const storesResource = createResource<Store[]>(async () => (await json<StoresFile>("/data/stores.json")).stores);
const tractsResource = createResource<TractsFile>(() => json<TractsFile>("/data/tracts.geojson"));
const metaResource = createResource<Meta>(() => json<Meta>("/data/meta.json"));

// Live API. Both calls are shared across pages.
const modelInfoResource = createResource<ModelInfo>(({ onSlow }) => getModelInfo({ onSlow }));

/** Scores for every scorable Mecklenburg store, one batched POST /predict. Keyed by Record ID (the API returns only the row index). */
export type Scores = Map<string, Prediction>;
const scoresResource = createResource<Scores>(async ({ onSlow }) => {
  const stores = (await json<StoresFile>("/data/stores.json")).stores.filter((s) => s.scorable);
  const preds = await predict(
    stores.map((s) => s.inputs),
    { onSlow },
  );
  return new Map(stores.map((s, i) => [s.record_id, preds[i]]));
});

export const useStores = () => useResource(storesResource);
export const useTracts = () => useResource(tractsResource);
export const useMeta = () => useResource(metaResource);
export const useModelInfo = () => useResource(modelInfoResource);
export const useScores = () => useResource(scoresResource);

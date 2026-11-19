"use client";

import { useMemo } from "react";
import { useMeta, useModelInfo, useScores, useStores } from "./data";
import { percentile } from "./format";
import type { Meta, Prediction, Store } from "./types";

export interface Row {
  store: Store;
  pred?: Prediction;
  /** share of scored Mecklenburg stores with a lower probability, whole percent */
  pct?: number;
  /** "typical" exit rate for this store type, 2012-2021 (meta.json) */
  typical?: number;
}

/** Static store data joined with the live scores and the type rates. Rows are sorted by probability, highest first; unscored stores last. */
export function useRows() {
  const stores = useStores();
  const scores = useScores();
  const meta = useMeta();
  const info = useModelInfo();

  const rows = useMemo<Row[]>(() => {
    if (!stores.data) return [];
    const all = scores.data ? [...scores.data.values()].map((p) => p.probability) : [];
    const m: Meta | undefined = meta.data;
    return stores.data
      .map((store) => {
        const pred = scores.data?.get(store.record_id);
        return {
          store,
          pred,
          pct: pred ? percentile(pred.probability, all) : undefined,
          typical: m?.type_rates.by_type[store.store_type]?.rate,
        };
      })
      .sort((a, b) => (b.pred?.probability ?? -1) - (a.pred?.probability ?? -1));
  }, [stores.data, scores.data, meta.data]);

  return { rows, stores, scores, meta, info };
}

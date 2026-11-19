"use client";

import { useEffect, useSyncExternalStore } from "react";

/**
 * A tiny shared loader. State lives at module level, so a page that was already loaded shows instantly when you navigate back, and
 * every component reading the same resource shares one request. `slow` turns true when the loader reports it is still waiting
 * (the API cold start); `retry()` runs the loader again after an error.
 */
export interface ResourceState<T> {
  status: "idle" | "loading" | "success" | "error";
  data?: T;
  error?: Error;
  slow: boolean;
}

export interface Resource<T> {
  subscribe(cb: () => void): () => void;
  getSnapshot(): ResourceState<T>;
  run(): void;
  retry(): void;
}

const IDLE: ResourceState<never> = { status: "idle", slow: false };

export function createResource<T>(load: (ctx: { onSlow: () => void }) => Promise<T>): Resource<T> {
  let state: ResourceState<T> = IDLE;
  let token = 0;
  const subs = new Set<() => void>();
  const set = (s: ResourceState<T>) => {
    state = s;
    subs.forEach((f) => f());
  };
  const run = () => {
    if (state.status === "loading") return;
    const mine = ++token;
    set({ status: "loading", data: state.data, slow: false });
    load({ onSlow: () => mine === token && state.status === "loading" && set({ ...state, slow: true }) }).then(
      (data) => mine === token && set({ status: "success", data, slow: false }),
      (error) => mine === token && set({ status: "error", error: error instanceof Error ? error : new Error(String(error)), slow: false }),
    );
  };
  return {
    subscribe: (cb) => {
      subs.add(cb);
      return () => subs.delete(cb);
    },
    getSnapshot: () => state,
    run,
    retry: run,
  };
}

export function useResource<T>(r: Resource<T>) {
  const s = useSyncExternalStore(r.subscribe, r.getSnapshot, () => IDLE as ResourceState<T>);
  useEffect(() => {
    if (r.getSnapshot().status === "idle") r.run();
  }, [r]);
  return { ...s, retry: r.retry, loading: s.status === "idle" || s.status === "loading" };
}

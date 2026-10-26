/**
 * Lightweight typed event emitter for decoupling UI modules without circular dependencies.
 */
import type { LookupResultItem } from "./types.js";

export interface AppEvents {
  "render": () => void;
  "scan": (skipScrape?: boolean) => Promise<void> | void;
  "loadConfig": (isInitialLoad?: boolean) => Promise<void> | void;
  "openAddModal": (type: string, index: number) => void;
  "openAddModalFromLookup": (res: LookupResultItem, type: string, card?: HTMLElement | null) => void;
  "openSettingsModal": () => void;
  "notify": (message: string, type?: "info" | "success" | "error" | string) => void;
  "applyTabFilter": () => void;
}

type EventKey = keyof AppEvents;
type Handler<K extends EventKey> = AppEvents[K];
type GenericHandler = (...args: unknown[]) => unknown;

const listeners: Map<string, Set<GenericHandler>> = new Map();

export function on<K extends EventKey>(event: K, handler: Handler<K>): () => void {
  let set = listeners.get(event);
  if (!set) {
    set = new Set();
    listeners.set(event, set);
  }
  const generic = handler as unknown as GenericHandler;
  set.add(generic);
  return () => {
    set?.delete(generic);
  };
}

export function emit<K extends EventKey>(event: K, ...args: Parameters<Handler<K>>): void {
  const set = listeners.get(event);
  if (!set) return;
  for (const handler of Array.from(set)) {
    handler(...args);
  }
}

export function clearAllListeners(): void {
  listeners.clear();
}

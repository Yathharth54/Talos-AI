import { useSyncExternalStore } from "react";

export type Action<S> = { type: "set"; patch: Partial<S> } | { type: "update"; fn: (s: S) => S } | { type: "reset"; state: S };

export function reduce<S>(state: S, action: Action<S>): S {
  switch (action.type) {
    case "set":
      return { ...state, ...action.patch };
    case "update":
      return action.fn(state);
    case "reset":
      return action.state;
  }
}

export interface Store<S> {
  get(): S;
  dispatch(action: Action<S>): void;
  set(patch: Partial<S>): void;
  update(fn: (s: S) => S): void;
  subscribe(listener: () => void): () => void;
}

/** One reducer per concern, readable synchronously by the player and the demo transport (ruling 6). */
export function createStore<S>(initial: S): Store<S> {
  let state = initial;
  const listeners = new Set<() => void>();
  const dispatch = (action: Action<S>) => {
    const next = reduce(state, action);
    if (next === state) return;
    state = next;
    for (const l of [...listeners]) l();
  };
  return {
    get: () => state,
    dispatch,
    set: (patch) => dispatch({ type: "set", patch }),
    update: (fn) => dispatch({ type: "update", fn }),
    subscribe: (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}

/** The selector must return a value already in the state (see the Selectors rule). */
export function useStoreState<S, T>(store: Store<S>, select: (s: S) => T): T {
  return useSyncExternalStore(store.subscribe, () => select(store.get()), () => select(store.get()));
}

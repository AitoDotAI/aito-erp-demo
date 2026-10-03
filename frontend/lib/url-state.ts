/**
 * A view's shareable selection, kept in the URL next to `?tenant=`.
 *
 * Only for state worth sending to someone — the PO or supplier a
 * colleague should look at — not for every toggle. `replaceState`, not a
 * push: picking a row is not a navigation, and Back should leave the
 * view rather than step through every row clicked.
 */

import { searchWithParam } from "./tenants";

export function readParam(key: string): string | null {
  if (typeof window === "undefined") return null;
  return new URLSearchParams(window.location.search).get(key);
}

export function writeParam(key: string, value: string | null): void {
  if (typeof window === "undefined") return;
  const { pathname, search, hash } = window.location;
  const wanted = searchWithParam(search, key, value);
  if (wanted !== search) {
    window.history.replaceState(window.history.state, "", pathname + wanted + hash);
  }
}

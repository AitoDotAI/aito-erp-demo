"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

import { usePathname } from "next/navigation";

import {
  DEFAULT_TENANT_ID,
  TenantId,
  TenantProfile,
  getTenant,
  resolveInitialTenant,
  searchWithTenant,
} from "./tenants";

import { TENANT_STORAGE_KEY as STORAGE_KEY, activeTenant } from "./api";

interface TenantContextValue {
  tenant: TenantProfile;
  tenantId: TenantId;
  setTenantId: (id: TenantId) => void;
  /** Helper: should a route be visible for the current tenant? */
  isVisible: (route: string) => boolean;
}

const TenantContext = createContext<TenantContextValue | null>(null);

export function TenantProvider({ children }: { children: ReactNode }) {
  const [tenantId, setTenantIdState] = useState<TenantId>(DEFAULT_TENANT_ID);

  const pathname = usePathname();

  // The URL and the tenant are kept in step, both ways. On load, on every
  // route change and on back/forward: the URL's `?tenant=` wins, else the
  // persisted choice, else a tenant that shows this view — and the result
  // is written back into the address bar. Before, the tenant lived only in
  // localStorage, so a copied link opened under the RECIPIENT's tenant and
  // in-app navigation dropped it from the URL.
  //
  // `replaceState`, not a push: the URL is being corrected, not navigated.
  // Back therefore returns to the previous route WITH the tenant it had,
  // and the popstate handler switches to it.
  const syncWithUrl = useCallback(() => {
    if (typeof window === "undefined") return;
    activeTenant();   // first call per load resolves from the URL; see api.ts
    const { pathname: path, search, hash } = window.location;
    const id = resolveInitialTenant(path, search, localStorage.getItem(STORAGE_KEY));
    localStorage.setItem(STORAGE_KEY, id);
    setTenantIdState(id);
    const wanted = searchWithTenant(search, id);
    if (wanted !== search) {
      window.history.replaceState(window.history.state, "", path + wanted + hash);
    }
  }, []);

  useEffect(() => { syncWithUrl(); }, [pathname, syncWithUrl]);

  useEffect(() => {
    window.addEventListener("popstate", syncWithUrl);
    return () => window.removeEventListener("popstate", syncWithUrl);
  }, [syncWithUrl]);

  const setTenantId = useCallback((id: TenantId) => {
    setTenantIdState(id);
    if (typeof window !== "undefined") {
      localStorage.setItem(STORAGE_KEY, id);
      // A switch is a navigation, so it is PUSHED: Back undoes it (the
      // popstate sync restores the old tenant from the old URL). It is a
      // different company, so earlier selections (a PO, a supplier) are
      // not carried over — only the tenant.
      const { pathname: path, search, hash } = window.location;
      const wanted = searchWithTenant("", id);
      if (wanted !== search) {
        window.history.pushState(window.history.state, "", path + wanted + hash);
      }
    }
  }, []);

  const tenant = getTenant(tenantId);

  const isVisible = useCallback(
    (route: string) => !tenant.hideRoutes.includes(route),
    [tenant],
  );

  return (
    <TenantContext.Provider value={{ tenant, tenantId, setTenantId, isVisible }}>
      {children}
    </TenantContext.Provider>
  );
}

export function useTenant(): TenantContextValue {
  const ctx = useContext(TenantContext);
  if (!ctx) {
    // Allow components to render outside the provider during SSR — they
    // fall back to the default tenant. The hydrated client will swap in
    // the persisted choice via useEffect above.
    const tenant = getTenant(DEFAULT_TENANT_ID);
    return {
      tenant,
      tenantId: DEFAULT_TENANT_ID,
      setTenantId: () => {},
      isVisible: (route: string) => !tenant.hideRoutes.includes(route),
    };
  }
  return ctx;
}

"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

import {
  DEFAULT_TENANT_ID,
  TenantId,
  TenantProfile,
  getTenant,
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

  // Load the tenant on mount: `?tenant=`, else the persisted choice, else
  // one that shows this view (see activeTenant / resolveInitialTenant).
  useEffect(() => {
    if (typeof window === "undefined") return;
    setTenantIdState(activeTenant());
  }, []);

  const setTenantId = useCallback((id: TenantId) => {
    setTenantIdState(id);
    if (typeof window !== "undefined") {
      localStorage.setItem(STORAGE_KEY, id);
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

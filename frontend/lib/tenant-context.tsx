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
  TENANTS,
  TenantId,
  TenantProfile,
  getTenant,
} from "./tenants";

const STORAGE_KEY = "demoTenant";

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

  // Load persisted choice on mount.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored && TENANTS.some((t) => t.id === stored)) {
      setTenantIdState(stored as TenantId);
    }
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

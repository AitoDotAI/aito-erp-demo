// Which tenant a page load starts in. Run: npm test (Node >= 22.6).
import assert from "node:assert/strict";
import { test } from "node:test";

import { DEFAULT_TENANT_ID, hidesRoute, getTenant, resolveInitialTenant } from "./tenants.ts";

test("?tenant= wins over the stored choice", () => {
  assert.equal(resolveInitialTenant("/po-queue/", "?tenant=studio", "aurora"), "studio");
});

test("the stored choice is used when the URL names no tenant", () => {
  assert.equal(resolveInitialTenant("/po-queue/", "", "studio"), "studio");
});

test("an unknown ?tenant= or stored value falls back", () => {
  assert.equal(resolveInitialTenant("/po-queue/", "?tenant=nope", null), DEFAULT_TENANT_ID);
  assert.equal(resolveInitialTenant("/po-queue/", "?tenant=nope", "aurora"), "aurora");
  assert.equal(resolveInitialTenant("/po-queue/", "", "garbage"), DEFAULT_TENANT_ID);
});

// The live bugs: a cold visit (nothing stored) to these views landed on the
// default tenant, which hides them - /matching/ rendered empty and
// /recommendations/ errored. Only Aurora has a product catalogue.
test("a cold deep link to an Aurora-only view opens it as Aurora", () => {
  assert.ok(hidesRoute(getTenant(DEFAULT_TENANT_ID), "/matching/"));
  assert.equal(resolveInitialTenant("/matching/", "", null), "aurora");
  assert.equal(resolveInitialTenant("/recommendations/", "", null), "aurora");
  assert.equal(resolveInitialTenant("/recommendations", "", "studio"), "aurora");
});

test("a tenant that shows the view is kept", () => {
  assert.equal(resolveInitialTenant("/projects/", "", "studio"), "studio");
  assert.equal(resolveInitialTenant("/matching/", "?tenant=aurora", "metsa"), "aurora");
});

test("route matching is by path segment, not prefix", () => {
  // "/projects" is hidden for aurora; "/project-plan" must not match it.
  const aurora = getTenant("aurora");
  assert.ok(hidesRoute(aurora, "/projects"));
  assert.ok(hidesRoute(aurora, "/projects/"));
  assert.ok(!hidesRoute(aurora, "/projectsx"));
});

// "I can send a view, but not for a specific tenant": the address bar
// never carried the tenant, so a copied link opened under the
// recipient's own stored choice. The URL is now kept in step with it.
import { searchWithTenant, searchWithParam } from "./tenants.ts";

test("the tenant is written into the query, keeping everything else", () => {
  assert.equal(searchWithTenant("", "aurora"), "?tenant=aurora");
  assert.equal(searchWithTenant("?po=PO-1001", "studio"), "?po=PO-1001&tenant=studio");
  assert.equal(searchWithTenant("?tenant=metsa&po=PO-1", "aurora"), "?tenant=aurora&po=PO-1");
});

test("a link built for every view round-trips to the same tenant, cold", () => {
  // A fresh browser has nothing stored; the stored value below is the
  // recipient's OWN choice, which the link must win over.
  for (const t of ["metsa", "aurora", "studio"]) {
    for (const route of ["/po-queue/", "/supplier/", "/anomalies/", "/inventory/", "/overview/"]) {
      if (hidesRoute(getTenant(t), route)) continue;
      const link = route + searchWithTenant("", t);
      const [path, search] = link.split("?");
      for (const stored of [null, "metsa", "aurora", "studio"]) {
        assert.equal(resolveInitialTenant(path, "?" + search, stored), t, `${link} with ${stored} stored`);
      }
    }
  }
});

test("a view's selection is a param of its own, and clearing it removes it", () => {
  assert.equal(searchWithParam("?tenant=aurora", "supplier", "Valio Oy"), "?tenant=aurora&supplier=Valio+Oy");
  assert.equal(searchWithParam("?tenant=aurora&po=PO-1", "po", null), "?tenant=aurora");
});

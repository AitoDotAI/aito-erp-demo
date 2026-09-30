// The pane picks the recorded query behind the row, and renders it safely. Run: npm test.
import assert from "node:assert/strict";
import { test } from "node:test";

import { findQuery, queryHtml } from "./query.ts";

const recorded = [
  { endpoint: "_search", body: { from: "purchases", where: { supplier: "Elenia Oy" }, limit: 1 } },
  { endpoint: "_predict", body: { from: "purchases", where: { supplier: "Elenia Oy" }, predict: "approver" } },
  { endpoint: "_predict", body: { from: "purchases", where: { supplier: "Telia Finland" }, predict: "approver" } },
  { endpoint: "_relate", body: { from: "baskets", where: { products: { $has: "SKU-1" } }, relate: ["products"] } },
];

test("the row's own query, not the first of its shape", () => {
  const q = findQuery(recorded, { endpoint: "_predict", target: "approver", where: { supplier: "Telia Finland" } });
  assert.equal(q, recorded[2]);
});

test("a where clause is compared by value, operators included", () => {
  assert.equal(findQuery(recorded, { where: { products: { $has: "SKU-1" } } }), recorded[3]);
  assert.equal(findQuery(recorded, { where: { products: { $has: "SKU-2" } } }), null);
});

test("v2's list-valued relate matches a field name", () => {
  assert.equal(findQuery(recorded, { target: "products" }), recorded[3]);
});

test("nothing recorded means no pane, not a sample", () => {
  assert.equal(findQuery(undefined, { endpoint: "_predict" }), null);
  assert.equal(findQuery(recorded, { endpoint: "_estimate" }), null);
});

test("values from the data are escaped once", () => {
  const html = queryHtml({ endpoint: "_search", body: { from: "t", where: { name: "<b>A & B</b>" } } }, "v2");
  assert.ok(html.includes("&lt;b&gt;A &amp; B&lt;/b&gt;"));
  assert.ok(!html.includes("<b>A"));
  assert.ok(html.startsWith('<span class="q-k">POST</span> /api/v2/_search'));
});

test("the predicted field is highlighted, other strings are values", () => {
  const html = queryHtml(recorded[1], "v2");
  assert.ok(html.includes('<span class="q-p">&quot;approver&quot;</span>'));
  assert.ok(html.includes('<span class="q-v">&quot;Elenia Oy&quot;</span>'));
});

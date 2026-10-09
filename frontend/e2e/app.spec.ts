import { expect, type Page, test } from "@playwright/test";
import { blankStyle, geocodeResults, heatmap, plan } from "./fixtures";

interface Captured {
  planBody?: Record<string, unknown>;
  heatmapBody?: Record<string, unknown>;
  consoleErrors: string[];
}

async function mockApi(page: Page, opts: { planStatus?: number } = {}): Promise<Captured> {
  const captured: Captured = { consoleErrors: [] };
  page.on("console", (m) => m.type() === "error" && captured.consoleErrors.push(m.text()));
  page.on("pageerror", (e) => captured.consoleErrors.push(e.message));

  await page.route("https://tiles.openfreemap.org/**", (r) => r.fulfill({ json: blankStyle }));
  await page.route("**/api/geocode/**", (r) => {
    const q = new URL(r.request().url()).searchParams.get("q")!.toLowerCase();
    const key = Object.keys(geocodeResults).find((k) => q.startsWith(k));
    return r.fulfill({ json: { results: key ? geocodeResults[key] : [] } });
  });
  await page.route("**/api/plan/", (r) => {
    captured.planBody = r.request().postDataJSON();
    if (opts.planStatus) {
      return r.fulfill({ status: opts.planStatus, json: { detail: "No drivable route was found between these locations." } });
    }
    return r.fulfill({ json: plan });
  });
  await page.route("**/api/heatmap/", (r) => {
    captured.heatmapBody = r.request().postDataJSON();
    return r.fulfill({ json: heatmap() });
  });
  return captured;
}

async function pickPlace(page: Page, label: string, query: string, option: RegExp) {
  await page.getByLabel(label, { exact: true }).fill(query);
  await page.getByRole("option", { name: option }).click();
}

async function planTrip(page: Page) {
  await page.goto("/");
  await pickPlace(page, "Origin", "Denver", /Denver, Colorado/);
  await pickPlace(page, "Destination", "Salt Lake", /Salt Lake City/);
  await page.getByLabel("Load (lb)").fill("42000");
  await page.getByRole("radio", { name: "10 mi" }).click();
  await page.getByRole("button", { name: "Find safest route" }).click();
  await expect(page.locator(".route-card")).toHaveCount(3);
}

test("plans a trip and recommends the safer route over the faster one", async ({ page }) => {
  const api = await mockApi(page);
  await planTrip(page);

  // Request sent to the API matches the form.
  expect(api.planBody).toMatchObject({
    origin: { label: "Denver, Colorado, US", lat: 39.7392, lon: -104.9903 },
    destination: { label: "Salt Lake City, Utah, US" },
    load_lbs: 42000,
    interval_miles: 10,
  });
  expect(new Date(api.planBody!.departure as string).getTime()).toBeGreaterThan(Date.now());

  // Recommendation and ranking order.
  await expect(page.getByText("Recommended: Route B")).toBeVisible();
  await expect(page.getByText(/Beats Route A on Severe miles/)).toBeVisible();
  await expect(page.locator(".route-card .route-badge")).toHaveText(["B", "C", "A"]);
  await expect(page.locator(".route-card").first()).toHaveAttribute("aria-pressed", "true");

  // Map: one summary label per route.
  await expect(page.locator(".route-label")).toHaveCount(3);
  await expect(page.locator(".route-label.selected")).toContainText("B");

  // Checkpoint table for the recommended route.
  await expect(page.getByRole("heading", { name: /Route B checkpoints/ })).toBeVisible();
  await expect(page.locator(".checkpoints tbody tr")).toHaveCount(11);

  // The heatmap is requested with every route's geometry, the departure and the load.
  await expect(page.locator(".play")).toBeEnabled();
  expect((api.heatmapBody!.routes as unknown[]).length).toBe(3);
  expect(api.heatmapBody).toMatchObject({ departure: plan.request.departure, load_lbs: 42000 });

  expect(api.consoleErrors).toEqual([]);
});

test("selecting another route shows its checkpoints, risk and load rule", async ({ page }) => {
  const api = await mockApi(page);
  await planTrip(page);

  await page.locator(".route-card", { hasText: "Max Severe" }).click();
  await expect(page.getByRole("heading", { name: /Route A checkpoints/ })).toBeVisible();
  await expect(page.locator(".route-label.selected")).toContainText("A");
  const severeRows = page.locator(".checkpoints tbody tr", { hasText: "Severe" });
  await expect(severeRows).toHaveCount(2);
  await expect(severeRows.first().locator(".risk-chip")).toHaveAttribute("title", /40,000 lb/);

  // Clicking a row opens that checkpoint's popup on the map.
  await severeRows.first().click();
  await expect(page.locator(".maplibregl-popup .cp-popup")).toContainText("Severe");
  await expect(page.locator(".maplibregl-popup .cp-rule")).toContainText("40,000 lb");

  expect(api.consoleErrors).toEqual([]);
});

test("heatmap slider, layers and legend follow the risk table", async ({ page }) => {
  const api = await mockApi(page);
  await planTrip(page);
  await expect(page.locator(".play")).toBeEnabled();

  await expect(page.locator(".hour-label")).toContainText("+0h");
  await page.locator(".slider").fill("5");
  await expect(page.locator(".hour-label")).toContainText("+5h");
  await expect(page.locator(".truck-text")).toContainText("Route B truck at");

  await page.getByRole("radio", { name: "Wind" }).click();
  await expect(page.locator(".legend")).toContainText("25–34");
  await expect(page.locator(".legend")).toContainText("≥55");
  await page.getByRole("radio", { name: "Rain" }).click();
  await expect(page.locator(".legend")).toContainText("0.50–1.00");
  await expect(page.locator(".legend")).toContainText(">1.00");

  // Playback advances the hour.
  await page.locator(".play").click();
  await expect(page.locator(".hour-label")).not.toContainText("+5h");
  await page.locator(".play").click();

  expect(api.consoleErrors).toEqual([]);
});

test("shows the server's message when planning fails", async ({ page }) => {
  await mockApi(page, { planStatus: 422 });
  await page.goto("/");
  await pickPlace(page, "Origin", "Denver", /Denver, Colorado/);
  await pickPlace(page, "Destination", "Salt Lake", /Salt Lake City/);
  await page.getByRole("button", { name: "Find safest route" }).click();
  await expect(page.getByRole("alert")).toContainText("No drivable route");
  await expect(page.locator(".route-card")).toHaveCount(0);
});

test("asks for places picked from the suggestions", async ({ page }) => {
  await mockApi(page);
  await page.goto("/");
  await page.getByLabel("Origin", { exact: true }).fill("somewhere unknown");
  await page.getByRole("button", { name: "Find safest route" }).click();
  await expect(page.locator(".form-error")).toContainText("Pick an origin and a destination");
});

test("mobile layout has no horizontal scrolling", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockApi(page);
  await planTrip(page);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
});

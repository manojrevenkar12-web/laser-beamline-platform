import { expect, test } from "@playwright/test";

test("the shift view shows the beamline, the interlocks and the diagnostics", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Beamline console" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Interlocks" })).toBeVisible();
  await expect(page.getByAltText("Near field camera frame")).toBeVisible();
  await expect(page.getByText("experiment shots fired")).toBeVisible();
});

test("calibration and evaluation views load", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Calibration" }).click();
  await expect(page.getByRole("heading", { name: "Interaction matrix" })).toBeVisible();
  await page.getByRole("button", { name: "Evaluation" }).click();
  await expect(page.getByRole("heading", { name: "Release gates" })).toBeVisible();
});

test("a failed load says what failed and offers a retry", async ({ page }) => {
  await page.route("**/data/shift.json", (route) => route.fulfill({ status: 500, body: "" }));
  await page.goto("/");
  await expect(page.getByRole("alert")).toContainText("Could not load the shift");
  await expect(page.getByRole("button", { name: "Load again" })).toBeVisible();
});

import { expect, test } from "@playwright/test";

test("loads app and streams one response", async ({ page }) => {
  await page.route("**/clear-session", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ success: true, message: "ok" }),
    });
  });

  await page.route("**/chat-stream", async (route) => {
    const body = [
      'data: {"type":"chunk","content":"Bonjour"}',
      "",
      'data: {"type":"chunk","content":" !"}',
      "",
      'data: {"type":"done"}',
      "",
    ].join("\n");

    await route.fulfill({
      status: 200,
      headers: {
        "content-type": "text/event-stream",
        "cache-control": "no-cache",
        connection: "keep-alive",
      },
      body,
    });
  });

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Turgot" })).toBeVisible();
  await page.locator("textarea").first().fill("Bonjour Turgot");
  await page.locator("button[type='submit']").click();
  await expect(page.getByText("Bonjour !", { exact: true })).toBeVisible();
});

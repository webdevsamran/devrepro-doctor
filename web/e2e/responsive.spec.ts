/**
 * The four widths the dashboard plan named, at the layout's own boundaries.
 *
 * The existing suite runs two viewports -- Desktop Chrome at 1280 and a Pixel 5
 * at 393 -- which leaves both ends of the plan's `360 / 768 / 1280 / 2560`
 * untested, and those ends are where the layout actually decides something.
 *
 * 768px is not an arbitrary extra width: it is `48rem` exactly, the breakpoint
 * where the sidebar becomes a bottom sheet. A `max-width` query includes its
 * own boundary, so 768 gets the phone layout and 769 does not, and the test
 * below asserts that on purpose -- somebody rewriting these as `min-width`
 * queries flips the boundary by one pixel and nothing else would notice.
 *
 * 2560px is the only width where `--content-max` does anything at all. Below
 * it the constraint is invisible; above it, it is the difference between a
 * readable column and a 2400px-wide line of text. Nothing tested it.
 *
 * Both themes throughout, because every token has two definitions and a layout
 * assertion that only ever runs in light mode is half a test.
 */
import { expect, test, type Page } from '@playwright/test'

import { serveReport } from './fixture'

/** `--content-max: 82rem`, in pixels at the 16px root size. */
const CONTENT_MAX = 82 * 16

/** `48rem`: at or below this the sidebar is a bottom sheet. */
const SHEET_BREAKPOINT = 48 * 16

const WIDTHS = [
  { label: 'small phone', width: 360, height: 780 },
  { label: 'tablet', width: SHEET_BREAKPOINT, height: 1024 },
  { label: 'laptop', width: 1280, height: 800 },
  { label: 'ultrawide', width: 2560, height: 1440 },
] as const

/** Routes with the widest content: long PATH values, tables, diffs, a grid. */
const ROUTES = ['overview', 'path', 'toolchains', 'findings', 'diff', 'fleet']

const THEMES = ['light', 'dark'] as const

/**
 * These set their own viewport, so running them under both Playwright projects
 * would run each assertion twice at a size neither project chose.
 */
test.beforeEach(async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'this file sets its own viewport')
  await serveReport(page)
})

async function useTheme(page: Page, theme: string): Promise<void> {
  // Before navigation, so the first paint is already correct rather than
  // measured mid-transition.
  await page.addInitScript((value) => {
    window.localStorage.setItem('devrepro:theme', value)
  }, theme)
}

/**
 * Where the sidebar has come to rest.
 *
 * Polled rather than measured once, because the sheet slides: changing the
 * viewport changes its transform, and a single `boundingBox()` immediately
 * afterwards samples whichever animation frame it landed on. The first version
 * of this file did exactly that and read the sheet's starting position as its
 * final one.
 */
async function sidebarTop(page: Page): Promise<number> {
  const box = await page.locator('.sidebar').boundingBox()
  return box?.y ?? Number.NaN
}

async function overflow(page: Page): Promise<number> {
  return page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
}

for (const { label, width, height } of WIDTHS) {
  test(`nothing scrolls sideways at ${width}px (${label})`, async ({ page }) => {
    await page.setViewportSize({ width, height })

    for (const theme of THEMES) {
      await useTheme(page, theme)
      for (const id of ROUTES) {
        await page.goto(`/#/${id}`)
        await expect(page.getByRole('heading').first()).toBeVisible({ timeout: 15_000 })
        const over = await overflow(page)
        expect(over, `/${id} at ${width}px in ${theme} overflows by ${over}px`).toBeLessThanOrEqual(
          1,
        )
      }
    }
  })
}

test('the reading column stops growing on an ultrawide display', async ({ page }) => {
  // The one width where `--content-max` is doing anything. Without it a finding
  // explanation is a single 2400px line, which is the width at which people
  // stop reading prose entirely.
  await page.setViewportSize({ width: 2560, height: 1440 })
  await page.goto('/#/findings')
  await expect(page.getByRole('heading').first()).toBeVisible()

  const box = await page.locator('.content').boundingBox()
  expect(box).not.toBeNull()
  expect(box!.width).toBeLessThanOrEqual(CONTENT_MAX + 1)

  // ...and centred in what is left, rather than pinned against the sidebar.
  const sidebar = await page.locator('.sidebar').boundingBox()
  const leftGutter = box!.x - (sidebar!.x + sidebar!.width)
  const rightGutter = 2560 - (box!.x + box!.width)
  expect(Math.abs(leftGutter - rightGutter)).toBeLessThanOrEqual(2)
})

test('the sidebar keeps its labels at laptop width', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto('/#/home')
  await expect(page.getByRole('heading').first()).toBeVisible()

  // Above 68rem the rail is expanded, so a nav item reads as a word rather than
  // as an icon somebody has to hover to identify.
  await expect(page.locator('.sidebar .sidebar-label').first()).toBeVisible()
})

test('768px is a phone, and 769px is not', async ({ page }) => {
  // `max-width: 48rem` includes its own boundary. Asserting both sides pins the
  // decision: a rewrite to `min-width` moves it by a pixel, silently.
  await page.goto('/#/home')
  await expect(page.getByRole('heading').first()).toBeVisible()

  await page.setViewportSize({ width: SHEET_BREAKPOINT, height: 1024 })
  await expect
    .poll(() => sidebarTop(page), { message: 'at 768px the sidebar rests at the bottom' })
    .toBeGreaterThan(1024 / 2)

  await page.setViewportSize({ width: SHEET_BREAKPOINT + 1, height: 1024 })
  await expect
    .poll(() => sidebarTop(page), { message: 'at 769px it is a rail down the side again' })
    .toBeLessThan(100)
})

test('the bottom sheet is reachable and does not cover the page it opened', async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 780 })
  await page.goto('/#/home')
  await expect(page.getByRole('heading').first()).toBeVisible()

  const toggle = page.getByRole('button', { name: /sidebar/i })
  await toggle.click()
  const link = page.getByRole('link', { name: 'PATH Explorer' })
  await expect(link).toBeVisible()
  await link.click()

  await expect(page).toHaveURL(/#\/path/)
  // The sheet closes on navigation, or it covers the route just chosen -- on a
  // 780px-tall screen a 68vh sheet leaves almost nothing of the page visible.
  await expect
    .poll(() => sidebarTop(page), { message: 'the sheet slides back down after navigating' })
    .toBeGreaterThan(780 - 100)
})

test('reduced motion removes the transitions, not the layout', async ({ page }) => {
  // Forced reduced-motion is the last of the plan's manual passes. The failure
  // it guards against is a sheet that animates open for somebody who asked the
  // operating system for no animation -- and the opposite one, a stylesheet
  // that disables motion by disabling the transform that positions it.
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.setViewportSize({ width: 360, height: 780 })
  await page.goto('/#/home')
  await expect(page.getByRole('heading').first()).toBeVisible()

  const duration = await page
    .locator('.sidebar')
    .evaluate((el) => getComputedStyle(el).transitionDuration)
  expect(parseFloat(duration)).toBeLessThan(0.05)

  await page.getByRole('button', { name: /sidebar/i }).click()
  await expect(page.getByRole('link', { name: 'PATH Explorer' })).toBeVisible()
  expect(await overflow(page)).toBeLessThanOrEqual(1)
})

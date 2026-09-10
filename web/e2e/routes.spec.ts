/**
 * Every route renders, in a real browser, without a console error.
 *
 * This is the coverage `PRODUCT_GAPS.md` gap 5 described as missing. The
 * failures it is aimed at are the ones jsdom cannot see: a lazy chunk that does
 * not resolve, a page that throws only once its module is actually evaluated,
 * an undefined CSS custom property, a layout that breaks at a phone width.
 *
 * The route list is imported from `nav.ts` rather than retyped, so a route
 * added to the sidebar is covered here the moment it is added -- a hand-copied
 * list would have gone stale on the first new page.
 */
import { expect, test, type ConsoleMessage, type Page } from '@playwright/test'

import { ALL_ITEMS } from '../src/nav'
import { serveNoReport, serveReport } from './fixture'

/**
 * Console noise that is not a defect.
 *
 * Most pages ask a local fleet server for data and fall back to clearly
 * labelled demo fixtures when it is absent, which is the correct behaviour and
 * produces a failed fetch in the log. Filtering it by message is deliberate:
 * ignoring *all* console errors would defeat the point of watching them.
 */
const EXPECTED_NOISE = [
  'Failed to load resource',
  'net::ERR_CONNECTION_REFUSED',
  'ERR_CONNECTION_REFUSED',
  'Failed to fetch',
]

function watchConsole(page: Page): string[] {
  const errors: string[] = []
  page.on('console', (message: ConsoleMessage) => {
    if (message.type() !== 'error') return
    const text = message.text()
    if (EXPECTED_NOISE.some((allowed) => text.includes(allowed))) return
    errors.push(text)
  })
  page.on('pageerror', (error) => errors.push(`uncaught: ${error.message}`))
  return errors
}

test.describe('every route', () => {
  test.beforeEach(async ({ page }) => {
    await serveReport(page)
  })

  for (const item of ALL_ITEMS) {
    test(`${item.id} renders`, async ({ page }) => {
      const errors = watchConsole(page)

      await page.goto(`/#/${item.id}`)

      // A heading proves the lazy chunk resolved and the component rendered,
      // rather than the shell painting its skeleton around a route that threw.
      await expect(page.getByRole('heading').first()).toBeVisible({ timeout: 15_000 })

      // ...and specifically *this* route's heading. Without the fixture above,
      // every one of these passed on the "Could not load report" heading, so
      // thirty-two tests were asserting the same error page.
      await expect(page.getByRole('heading', { name: /Could not load report/ })).toHaveCount(0)
      // `aria-busy` is the skeleton's own marker; if it is still present the
      // route never finished loading and the heading came from the shell.
      await expect(page.locator('[aria-busy="true"]')).toHaveCount(0)
      expect(errors, `console errors on /${item.id}`).toEqual([])
    })
  }
})

test('an unknown route does not leave a blank page', async ({ page }) => {
  await serveReport(page)
  await page.goto('/#/no-such-route')
  await expect(page.getByRole('heading').first()).toBeVisible()
})

test('a missing report is explained, not left blank', async ({ page }) => {
  // The state the route suite used to be testing thirty-two times by accident.
  // It deserves exactly one test, and it says what to do next.
  await serveNoReport(page)
  await page.goto('/#/overview')

  await expect(page.getByRole('alert')).toBeVisible()
  await expect(page.getByText('devrepro serve')).toBeVisible()
})

test('the page never scrolls sideways', async ({ page }) => {
  // Wide content -- PATH values, tables, code blocks -- has to scroll inside
  // its own box. A body that scrolls horizontally is the single most common
  // way a dashboard breaks on a phone.
  await serveReport(page)
  for (const id of ['path', 'toolchains', 'findings', 'diff', 'fleet']) {
    await page.goto(`/#/${id}`)
    await expect(page.getByRole('heading').first()).toBeVisible()
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    )
    expect(overflow, `/${id} overflows horizontally by ${overflow}px`).toBeLessThanOrEqual(1)
  }
})

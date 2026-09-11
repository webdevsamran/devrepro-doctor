/**
 * Accessibility, checked by a machine on every route.
 *
 * axe-core finds a specific and useful class of fault -- contrast below the
 * threshold, a control with no accessible name, a heading level skipped, a
 * region with no label. It cannot tell you whether the interface makes sense,
 * and passing it is not the same as being accessible. It is a floor, and this
 * project did not have one.
 *
 * Serious and critical only. axe's `minor` and `moderate` findings include
 * genuinely debatable calls, and a gate that fails on those gets disabled --
 * the same failure mode `guard --scope changed` exists to avoid on the CLI
 * side.
 *
 * **The tag list is the whole configuration, and it was wrong.** This project
 * claims WCAG 2.2 AA. The tags asked for 2.0 and 2.1 only, so the two criteria
 * 2.2 actually adds that axe can test were never run:
 *
 * - `target-size` (SC 2.5.8, AA) is tagged `wcag22aa`, which was absent.
 * - `label-content-name-mismatch` (SC 2.5.3, **Level A**) is tagged
 *   `experimental`, so axe ships it disabled and a tag list cannot reach it.
 *   It has to be turned on by name.
 *
 * The second one was not hypothetical: the command palette button read
 * "Jump to..." and was named "Open command palette", so somebody driving this
 * console by voice could say the words on the screen and have nothing happen.
 * Lighthouse found it; this suite had been passing over it on every route.
 */
import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'

import { ALL_ITEMS } from '../src/nav'
import { serveReport } from './fixture'

const IMPACT = new Set(['serious', 'critical'])

// Cards fade in on mount. axe computes the *effective* foreground, so running
// it mid-animation reported the accent chip at 2.84:1 when its settled value
// passes -- a gate that fails at random gets switched off. The app honours
// reduced motion by collapsing every duration to 0.01ms, so this measures the
// end state rather than sleeping and hoping.
test.use({ reducedMotion: 'reduce' })

// Same reason as the route suite: without a report every page was the error
// page, and axe was auditing one screen thirty-two times.
test.beforeEach(async ({ page }) => {
  await serveReport(page)
})

for (const item of ALL_ITEMS) {
  test(`${item.id} has no serious accessibility violations`, async ({ page }) => {
    await page.goto(`/#/${item.id}`)
    await expect(page.getByRole('heading').first()).toBeVisible({ timeout: 15_000 })

    const results = await new AxeBuilder({ page })
      // `options` replaces the whole option object and `withTags` only sets
      // `runOnly`, so this order keeps both. Reversed, the rule below silently
      // goes back to disabled.
      .options({ rules: { 'label-content-name-mismatch': { enabled: true } } })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
      .analyze()

    const serious = results.violations.filter((v) => IMPACT.has(v.impact ?? ''))
    const described = serious.map(
      (v) => `${v.id} (${v.impact}) on ${v.nodes.length}: ${v.nodes[0]?.target.join(' ')}`,
    )
    expect(described, `axe violations on /${item.id}`).toEqual([])
  })
}

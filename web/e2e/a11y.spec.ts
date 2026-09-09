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
 */
import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'

import { ALL_ITEMS } from '../src/nav'

const IMPACT = new Set(['serious', 'critical'])

// Cards fade in on mount. axe computes the *effective* foreground, so running
// it mid-animation reported the accent chip at 2.84:1 when its settled value
// passes -- a gate that fails at random gets switched off. The app honours
// reduced motion by collapsing every duration to 0.01ms, so this measures the
// end state rather than sleeping and hoping.
test.use({ reducedMotion: 'reduce' })

for (const item of ALL_ITEMS) {
  test(`${item.id} has no serious accessibility violations`, async ({ page }) => {
    await page.goto(`/#/${item.id}`)
    await expect(page.getByRole('heading').first()).toBeVisible({ timeout: 15_000 })

    const results = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
      .analyze()

    const serious = results.violations.filter((v) => IMPACT.has(v.impact ?? ''))
    const described = serious.map(
      (v) => `${v.id} (${v.impact}) on ${v.nodes.length}: ${v.nodes[0]?.target.join(' ')}`,
    )
    expect(described, `axe violations on /${item.id}`).toEqual([])
  })
}

import { existsSync } from 'node:fs'
import { join } from 'node:path'

import { expect, test } from '@playwright/test'

import { serveReport } from './fixture'

/**
 * Visual regression, on one route, in both themes.
 *
 * This is the Storybook-and-Chromatic shape of the problem without either.
 * Storybook is ~40 MB of devDependencies, its own build and its own config, and
 * a hosted visual-diff service is an account, a bill, and screenshots of a
 * developer's console leaving the machine — for a design system of about a
 * dozen components.
 *
 * The component gallery route is a better target than a set of stories anyway.
 * It renders every component in the *real* shell, so it inherits the real
 * tokens, the real theme toggle and the real reduced-motion setting; a
 * Storybook story renders in an iframe with its own decorators, which is
 * exactly where token drift hides. One screenshot covers the lot.
 *
 * Both themes, because every token has two definitions and the dark one is the
 * half nobody looks at. The `--surface-2` bug this project shipped for months —
 * a token referenced and never defined — is precisely what this catches.
 *
 * **Baselines are per-platform and are not committed from a developer's
 * machine.** A screenshot taken on Windows differs from one taken on Linux in
 * font rasterisation alone, so committing a Windows baseline would fail every
 * CI run on ubuntu and teach everybody to ignore this suite. Instead the test
 * *skips* where no baseline exists for the current platform, and says so.
 *
 * To adopt it on the platform your CI uses:
 *
 *     npx playwright test e2e/visual.spec.ts --update-snapshots
 *
 * then commit `e2e/visual.spec.ts-snapshots/`. From then on a changed
 * screenshot fails, which is the point.
 *
 * Skipping rather than failing is a real trade and worth naming: a suite that
 * silently passes because nobody generated a baseline is a suite that proves
 * nothing. The mitigation is that the skip is loud — Playwright prints the
 * reason — and that the print-media test below never skips, so this file always
 * asserts something.
 */

const THEMES = ['light', 'dark'] as const
const SNAPSHOT_DIR = join(import.meta.dirname, 'visual.spec.ts-snapshots')

for (const theme of THEMES) {
  test(`component gallery looks the same in ${theme}`, async ({ page }, testInfo) => {
    // Desktop only: a full-page screenshot of every component at two viewport
    // widths doubles the baselines to catch a layout difference the responsive
    // tests in routes.spec.ts already assert directly.
    test.skip(testInfo.project.name !== 'desktop', 'one viewport is enough for a token diff')

    const name = `gallery-${theme}.png`
    const platform = `${testInfo.project.name}-${process.platform}`
    test.skip(
      !existsSync(join(SNAPSHOT_DIR, `gallery-${theme}-${platform}.png`)) &&
        !existsSync(join(SNAPSHOT_DIR, name)),
      `No baseline for ${platform}. Generate one on the platform your CI uses: ` +
        'npx playwright test e2e/visual.spec.ts --update-snapshots',
    )

    await serveReport(page)
    // Set before navigation so the first paint is already correct: toggling
    // afterwards screenshots a transition, which is a flaky diff for a reason
    // that has nothing to do with the components.
    await page.addInitScript((value) => {
      window.localStorage.setItem('devrepro:theme', value)
    }, theme)

    await page.goto('/#/gallery')
    await expect(page.getByRole('heading', { name: 'Component gallery' })).toBeVisible()

    // The radial animates a count-up on mount. Waiting for it to settle keeps
    // the diff about the design rather than about timing.
    await page.waitForTimeout(600)

    await expect(page).toHaveScreenshot(name, {
      fullPage: true,
      // Sub-pixel text rendering differs between runs of the same browser on
      // the same OS. A tolerance wide enough to absorb that and narrow enough
      // to catch a colour or a layout change is the whole art here.
      maxDiffPixelRatio: 0.02,
    })
  })
}

test('the print stylesheet drops the shell', async ({ page }) => {
  // "Save as PDF" is the browser's own print dialogue, so the print stylesheet
  // *is* the PDF renderer. Without it the export carries the sidebar and a dark
  // background nobody asked to print, and nothing else in the suite exercises
  // `@media print` at all.
  //
  // No baseline needed, so this one always runs — which is what keeps this file
  // from being a suite that proves nothing on a machine with no snapshots.
  await serveReport(page)
  await page.goto('/#/gallery')
  await page.emulateMedia({ media: 'print' })

  await expect(page.locator('.sidebar')).toBeHidden()
  await expect(page.getByRole('heading', { name: 'Component gallery' })).toBeVisible()
})

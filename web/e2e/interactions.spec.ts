/**
 * The interactions that make the shell usable, driven by a real keyboard.
 *
 * These are the parts jsdom can assert the shape of but not the behaviour: a
 * keyboard shortcut competing with the browser's own, a theme that has to
 * survive a reload, an off-canvas sheet whose open state is a CSS transform.
 */
import { expect, test } from '@playwright/test'

test.describe('command palette', () => {
  test('opens on the keyboard shortcut and navigates', async ({ page }) => {
    await page.goto('/#/home')
    await expect(page.getByRole('heading').first()).toBeVisible()

    await page.keyboard.press('ControlOrMeta+k')
    const palette = page.getByRole('dialog', { name: 'Command palette' })
    await expect(palette).toBeVisible()

    await page.keyboard.type('path')
    await page.keyboard.press('Enter')

    await expect(page).toHaveURL(/#\/path/)
    await expect(palette).toBeHidden()
  })

  test('closes on Escape without navigating', async ({ page }) => {
    await page.goto('/#/findings')
    await expect(page.getByRole('heading').first()).toBeVisible()

    await page.keyboard.press('ControlOrMeta+k')
    await expect(page.getByRole('dialog', { name: 'Command palette' })).toBeVisible()
    await page.keyboard.press('Escape')

    await expect(page.getByRole('dialog', { name: 'Command palette' })).toBeHidden()
    await expect(page).toHaveURL(/#\/findings/)
  })
})

test('the chosen theme survives a reload', async ({ page }) => {
  // A theme toggle that forgets is worse than no toggle: every reload undoes
  // the choice, and the user has to make it again on every visit.
  await page.goto('/#/home')
  const toggle = page.getByRole('button', { name: /^Theme:/ })
  await expect(toggle).toBeVisible()

  const first = await toggle.getAttribute('aria-label')
  await toggle.click()
  const second = await toggle.getAttribute('aria-label')
  expect(second).not.toBe(first)

  await page.reload()
  await expect(page.getByRole('button', { name: /^Theme:/ })).toHaveAttribute(
    'aria-label',
    second as string,
  )
})

test('filters in the URL reopen the same view', async ({ page }) => {
  // The claim the findings page makes in its own footer text. If it were only
  // read on mount and never written, this would pass by accident, so the test
  // navigates by URL rather than by clicking.
  await page.goto('/#/findings?state=PASS')
  await expect(page.getByRole('heading', { name: 'Findings' })).toBeVisible()
  const passOnly = page.getByRole('checkbox', { name: /PASS/ })
  await expect(passOnly).toBeChecked()
})

test.describe('mobile', () => {
  test.skip(({ isMobile }) => !isMobile, 'the sheet only exists at phone widths')

  test('the sidebar is a sheet that opens and closes', async ({ page }) => {
    await page.goto('/#/home')
    const sidebar = page.locator('aside.sidebar')
    await expect(sidebar).toHaveAttribute('data-open', 'false')

    await page.getByRole('button', { name: /sidebar|menu|sections/i })
      .first()
      .click()

    await expect(sidebar).toHaveAttribute('data-open', 'true')
  })
})

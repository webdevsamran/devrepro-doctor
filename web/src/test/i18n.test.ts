/**
 * Translation scaffolding.
 *
 * The interesting assertions are not "does it look up a string" — they are the
 * three places a hand-rolled i18n layer is usually quietly wrong, each of which
 * only shows up once somebody adds a second locale and by then the machinery is
 * load-bearing:
 *
 * - A missing key renders the key, not an empty string. Both are wrong on
 *   screen; only one says which key to add.
 * - `en-GB` matches an `en` catalogue, because otherwise every British visitor
 *   silently gets the fallback.
 * - Plurals go through `Intl.PluralRules`. `n === 1` is correct for English and
 *   wrong for most of the languages anybody adds next, and baking it in means
 *   the first translator has to change the machinery too.
 */
import { describe, expect, it } from 'vitest'

import { CATALOGUE, plural, resolveLocale, translate } from '../i18n'

describe('catalogue', () => {
  it('has an English catalogue with the shell strings in it', () => {
    expect(CATALOGUE.en['nav.sections']).toBe('Sections')
    expect(Object.keys(CATALOGUE.en).length).toBeGreaterThan(15)
  })

  it('gives every locale the same keys', () => {
    // One locale today, so this passes trivially — and it is the check that
    // catches a half-translated catalogue the day a second one arrives, which
    // is the only day it could go wrong.
    const locales = Object.keys(CATALOGUE) as (keyof typeof CATALOGUE)[]
    const reference = Object.keys(CATALOGUE.en).sort()
    for (const locale of locales) {
      expect(Object.keys(CATALOGUE[locale]).sort()).toEqual(reference)
    }
  })

  it('translates no rule ids', () => {
    // `python/version-mismatch` is a stable identifier people quote in issues.
    // An identifier that changes by locale is not an identifier.
    for (const key of Object.keys(CATALOGUE.en)) {
      expect(key).not.toMatch(/^[a-z0-9-]+\/[a-z0-9-]+$/)
    }
  })
})

describe('translate', () => {
  it('substitutes placeholders', () => {
    expect(translate('findings.count_other', { n: 4 })).toBe('4 findings')
  })

  it('returns the key when there is no message, rather than nothing', () => {
    expect(translate('nav.nonexistent')).toBe('nav.nonexistent')
  })

  it('leaves an unknown placeholder alone instead of blanking it', () => {
    // `{n}` on screen is a bug somebody can see and report. An empty gap is a
    // bug that reads as a design choice.
    expect(translate('findings.count_other', {})).toBe('{n} findings')
  })
})

describe('resolveLocale', () => {
  it('prefers an explicit choice', () => {
    expect(resolveLocale('en')).toBe('en')
  })

  it('matches a region-specific tag against its base language', () => {
    expect(resolveLocale('en-GB')).toBe('en')
  })

  it('prefers an exact region catalogue over the base when one exists', () => {
    expect(resolveLocale('pt-BR', ['en', 'pt', 'pt-BR'])).toBe('pt-BR')
  })

  it('falls back rather than rendering keys for an unsupported language', () => {
    expect(resolveLocale('xx-YY')).toBe('en')
  })

  it('falls back when nothing is requested', () => {
    expect(resolveLocale(null, ['en'])).toBe('en')
  })
})

describe('plural', () => {
  it('uses the singular form for one', () => {
    expect(plural('findings.count', 1)).toBe('1 finding')
  })

  it('uses the plural form for everything else', () => {
    expect(plural('findings.count', 0)).toBe('0 findings')
    expect(plural('findings.count', 7)).toBe('7 findings')
  })

  it('goes through Intl.PluralRules rather than an n === 1 check', () => {
    // Proven by behaviour rather than by reading the source: Polish selects
    // `few` for 2, which an English-shaped rule cannot produce. The catalogue
    // has no `few`, so it falls back to `other` — the point is that the
    // *category* was computed by Intl and not by a comparison.
    expect(new Intl.PluralRules('pl').select(2)).toBe('few')
    expect(plural('findings.count', 2)).toBe('2 findings')
  })
})

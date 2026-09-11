/**
 * Translation scaffolding, and an honest account of what it can never cover.
 *
 * The scaffolding is small on purpose: a catalogue, a lookup, a locale that
 * follows the browser and can be overridden, and a build-time check that every
 * catalogue has the same keys. No library. `Intl` is in every browser this
 * targets, plural rules included, and an i18n framework here would be larger
 * than the console it translates.
 *
 * **What this can localise is the chrome, not the content.** That distinction
 * is the whole design and it is worth stating before anybody starts
 * translating:
 *
 * - Navigation labels, buttons, table headers, empty states — yes.
 * - **Findings — no.** A finding's summary and remediation hint come from the
 *   Python side, are generated per machine, and there are 159 documented rule
 *   ids. Translating those means translating the tool's diagnostic vocabulary,
 *   which is a different and much larger project — and a half-translated
 *   diagnostic, where the label is in French and the finding is in English, is
 *   worse than one consistently in English.
 * - **Rule ids — never.** `python/version-mismatch` is a stable identifier
 *   people quote in issues. An identifier that changes by locale is not an
 *   identifier.
 *
 * So this ships with `en` and the machinery. A second locale is a pull request
 * away and nobody has asked for one yet, which is why there is one catalogue
 * rather than a directory of half-finished ones.
 */

export type Locale = 'en'

/**
 * Every string the shell renders -- and only strings it renders.
 *
 * Flat keys: a nested catalogue reads better and diffs worse, and a translator
 * works in the diff.
 *
 * The first version of this file was written without looking at the components,
 * and it showed. It carried `state.empty: 'Nothing here yet'` for an empty state
 * that says "No {what} in this report.", six `severity.*` labels for badges that
 * deliberately print the uppercase enum so they match the CLI and the rule docs,
 * and an `action.retry` for a button that does not exist. A catalogue nobody
 * renders from is a catalogue that is wrong the moment it is written, and this
 * one was wrong on arrival.
 *
 * Every entry below is now the exact template a component passes to `t`, and
 * `tests/i18n.test.ts` fails on any key nothing uses.
 */
export const CATALOGUE = {
  en: {
    // --- shell ---
    'nav.skip': 'Skip to content',
    'nav.sections': 'Sections',
    'nav.home': 'DevRepro Doctor, home',
    'nav.jump': 'Jump to…',
    'nav.collapse': 'Collapse sidebar',
    'nav.expand': 'Expand sidebar',
    'nav.breadcrumb': 'Breadcrumb',

    // The theme button announced `Theme: dark.` -- the enum, lower-cased, as
    // stored. These are the words for it.
    'theme.cycle': 'Theme: {name}. Click to change.',
    'theme.light': 'Light',
    'theme.dark': 'Dark',
    'theme.system': 'System',

    // --- actions ---
    'action.copy': 'Copy',
    'action.copied': 'Copied',
    'action.copyMarkdown': 'Copy as Markdown',
    'action.copyAnnounce': '{label} copied to clipboard',
    'action.print': 'Print / Save as PDF',
    'action.filterSeverity': 'Filter by severity',
    'action.searchFindings': 'Search findings',

    // --- states ---
    'state.loading': 'Loading {what}…',
    'state.loadingDefault': 'sanitized scan data',
    'state.loadingView': 'Loading view…',
    'state.errorTitle': 'Could not load report',
    'state.empty': 'No {what} in this report.',
    'state.demo':
      'DEMO DATA — {what} is not available from this machine. Nothing here reflects your environment.',

    // --- counts ---
    // `plural` rather than `n === 1 ? ... : ...` at the call site: English has
    // two forms and most of the languages anybody adds next do not.
    'findings.count_one': '{n} finding',
    'findings.count_other': '{n} findings',
    'findings.showing': '{count} of {total} shown. Filters are in the URL, so this view can be linked to.',
  },
} as const satisfies Record<Locale, Record<string, string>>

export type MessageKey = keyof (typeof CATALOGUE)['en']

const FALLBACK: Locale = 'en'

/**
 * The locale to render in.
 *
 * An explicit choice wins over the browser's, and the browser's wins over the
 * fallback. An unsupported language falls back rather than rendering keys:
 * `nav.sections` on screen is worse than English on screen.
 */
export function resolveLocale(
  requested?: string | null,
  available: readonly string[] = Object.keys(CATALOGUE),
): Locale {
  const candidates = [requested, ...(typeof navigator === 'undefined' ? [] : navigator.languages)]
  for (const candidate of candidates) {
    if (!candidate) continue
    // `en-GB` should match an `en` catalogue. Region-specific catalogues take
    // precedence when one exists, which is why the exact match is tried first.
    if (available.includes(candidate)) return candidate as Locale
    const base = candidate.split('-')[0]
    if (available.includes(base)) return base as Locale
  }
  return FALLBACK
}

/**
 * Look up a message, substituting `{name}` placeholders.
 *
 * A missing key returns the key itself rather than an empty string. Both are
 * wrong on screen, and only one of them tells you which key to add.
 */
export function translate(
  key: MessageKey | string,
  values: Record<string, string | number> = {},
  locale: Locale = FALLBACK,
): string {
  const catalogue: Record<string, string> = CATALOGUE[locale] ?? CATALOGUE[FALLBACK]
  const template = catalogue[key] ?? CATALOGUE[FALLBACK][key as MessageKey] ?? key
  return template.replace(/\{(\w+)\}/g, (whole, name: string) =>
    name in values ? String(values[name]) : whole,
  )
}

/**
 * A count with its plural form, via `Intl.PluralRules`.
 *
 * Not `n === 1 ? one : other`. That rule is correct for English and wrong for
 * most of the languages anybody would add next — Polish has three forms,
 * Arabic six — and hard-coding the English rule into the machinery guarantees
 * the first translator has to change the machinery too.
 */
export function plural(
  key: string,
  n: number,
  locale: Locale = FALLBACK,
): string {
  const rules = new Intl.PluralRules(locale)
  const category = rules.select(n)
  const exact = `${key}_${category}`
  const fallbackKey = `${key}_other`
  const catalogue: Record<string, string> = CATALOGUE[locale] ?? CATALOGUE[FALLBACK]
  const chosen = catalogue[exact] !== undefined ? exact : fallbackKey
  return translate(chosen, { n }, locale)
}

/**
 * The locale this session renders in, resolved once.
 *
 * There is no switcher: with one catalogue a switcher is a control that changes
 * nothing. `resolveLocale()` reads the browser, so adding a second catalogue is
 * the only change a second language needs.
 */
export const LOCALE: Locale = resolveLocale()

/**
 * Look up a message in the session locale.
 *
 * Typed to `MessageKey`, so a key that is not in the catalogue fails the
 * typecheck rather than rendering `nav.jomp` to a user. `translate` keeps its
 * wider signature because the fallback behaviour it documents -- return the key
 * -- is what a runtime-composed key needs.
 */
export function t(key: MessageKey, values: Record<string, string | number> = {}): string {
  return translate(key, values, LOCALE)
}

/** A pluralised count in the session locale. */
export function tn(key: 'findings.count', n: number): string {
  return plural(key, n, LOCALE)
}

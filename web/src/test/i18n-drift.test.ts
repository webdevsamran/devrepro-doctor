/**
 * The catalogue and the console, held to each other.
 *
 * The machinery in `i18n.test.ts` was always correct. The catalogue was not:
 * it had been written without reference to the components, and shipped
 * `state.empty: 'Nothing here yet'` for an empty state that reads "No {what} in
 * this report.", six `severity.*` labels for badges that deliberately print the
 * uppercase enum, and an `action.retry` for a button that does not exist. Every
 * one of its strings was also hardcoded somewhere else, so nothing rendered
 * from it at all.
 *
 * That is not a translation bug. It is the same bug this project exists to find
 * in other people's repositories: a file that claims to be the source of truth
 * for something it has never looked at. Two assertions keep it from coming
 * back -- an entry nobody renders is a lie waiting to happen, and a literal in
 * a component is an entry that will never be translated.
 */
import { describe, expect, it } from 'vitest'

import { CATALOGUE } from '../i18n'

/**
 * Every source file, read by Vite rather than by `node:fs`.
 *
 * `fs` would need `@types/node`, which this project does not have and should
 * not acquire for one test. `import.meta.glob` is a Vite feature, vitest runs
 * through Vite, and the files arrive as strings with no new dependency and no
 * path handling to get wrong on Windows.
 */
const MODULES = import.meta.glob('../**/*.{ts,tsx}', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>

const FILES = Object.entries(MODULES)
  // The tests quote the catalogue on purpose; that is their job. `i18n.ts` is
  // where the catalogue lives, so every value is in it by definition.
  //
  // Glob keys are relative to *this* file, so the rest of `src/test/` arrives
  // as `./name.test.ts` rather than `../test/name.test.ts`. Matching the wrong
  // one of those is why this filter is written by directory and not by prefix.
  .filter(([path]) => !path.startsWith('./') && path !== '../i18n.ts')
  .map(([path, text]) => ({ path: path.replace('../', ''), text }))

const ALL = FILES.map((file) => file.text).join('\n')

// A scan that finds nothing passes both assertions below without checking
// anything, which is the way a test like this dies quietly.
it('is actually reading the console', () => {
  expect(FILES.length).toBeGreaterThan(10)
  expect(ALL).toContain('CommandPalette')
})

/**
 * Source with its comments removed.
 *
 * A comment that quotes a catalogue string is doing its job -- the fix for the
 * palette button is explained in `App.tsx` by quoting the words that were
 * wrong -- and flagging that as untranslated prose would teach everyone to stop
 * writing the explanation. Line comments are only stripped when they start a
 * line, so a `https://` inside a string literal survives.
 */
function code(text: string): string {
  return text
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .split('\n')
    .filter((line) => !/^\s*\/\//.test(line))
    .join('\n')
}

/** Quoted string literals and JSX text nodes, exactly as written. */
function literals(text: string): string[] {
  const found: string[] = []
  for (const [, value] of text.matchAll(/'([^'\n]*)'/g)) found.push(value)
  for (const [, value] of text.matchAll(/"([^"\n]*)"/g)) found.push(value)
  // JSX text between tags, collapsed the way a browser collapses it.
  for (const [, value] of text.matchAll(/>([^<>{}]+)</g)) {
    const collapsed = value.replace(/\s+/g, ' ').trim()
    if (collapsed) found.push(collapsed)
  }
  return found
}

/**
 * Key prefixes built at runtime, as in ``t(`theme.${theme}`)``.
 *
 * Without this the three theme labels read as unused, and the obvious response
 * -- delete them -- would break the theme button. A composed key is still a
 * used key; it just cannot be found by searching for the whole thing.
 */
const COMPOSED = [...ALL.matchAll(/\bt\(`([a-z]+\.)\$\{/g)].map(([, prefix]) => prefix)

describe('the catalogue describes what the console renders', () => {
  it('has no entry that nothing renders', () => {
    const unused = Object.keys(CATALOGUE.en).filter((key) => {
      // `findings.count_one` is reached as `tn('findings.count', n)`: the plural
      // category comes from Intl, so the suffix never appears in the source.
      const stem = key.replace(/_(zero|one|two|few|many|other)$/, '')
      if (ALL.includes(`'${key}'`) || ALL.includes(`'${stem}'`)) return false
      return !COMPOSED.some((prefix) => key.startsWith(prefix))
    })
    expect(unused, 'catalogue keys no component asks for').toEqual([])
  })

  it('has no value a component also hardcodes', () => {
    const values = new Set<string>(Object.values(CATALOGUE.en))
    const offenders: string[] = []
    for (const { path, text } of FILES) {
      for (const literal of literals(code(text))) {
        if (values.has(literal)) offenders.push(`${path}: ${JSON.stringify(literal)}`)
      }
    }
    expect(offenders, 'strings that will never be translated').toEqual([])
  })
})

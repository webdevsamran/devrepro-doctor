/**
 * What the console is allowed to fetch a report from.
 *
 * CodeQL raised this as client-side request forgery on three loaders, and the
 * label undersells it for this particular page. `?src=` went from a link
 * straight into `fetch`, and whatever came back was rendered as a reading of
 * the reader's own machine. The payload is not a redirect or a leaked header —
 * it is a fabricated diagnosis of a computer nobody looked at, presented with
 * the authority of a local tool.
 *
 * The dashboard plan states the rule this breaks: a fake green score is worse
 * than an empty state, because the empty state cannot mislead.
 */
import { describe, expect, it } from 'vitest'

import { candidatesFor, resolveSource, sourceOverride } from '../api/source'

const PAGE = 'http://localhost:3000/index.html'

describe('resolveSource', () => {
  it('accepts a relative path beside the page', () => {
    expect(resolveSource('report.json', PAGE)).toBe('http://localhost:3000/report.json')
    expect(resolveSource('./exports/report.json', PAGE)).toBe(
      'http://localhost:3000/exports/report.json',
    )
  })

  it('accepts an absolute path on the same origin', () => {
    expect(resolveSource('/api/report', PAGE)).toBe('http://localhost:3000/api/report')
  })

  it.each([
    'https://example.invalid/clean.json',
    'http://example.invalid/clean.json',
    '//example.invalid/clean.json',
    'http://localhost:9999/clean.json',
  ])('refuses another origin: %s', (candidate) => {
    expect(resolveSource(candidate, PAGE)).toBeNull()
  })

  it.each([
    // The two bypasses an origin check is usually got with. `URL` parses both
    // correctly -- the first has userinfo `localhost:3000` on the host
    // `example.invalid`, the second a host merely *starting* with it -- but a
    // check written against `href.startsWith(...)` or a hostname substring
    // would accept both, and those are the checks people write.
    'http://localhost:3000@example.invalid/clean.json',
    'https://localhost:3000.example.invalid/clean.json',
  ])('refuses a host that only looks like this one: %s', (candidate) => {
    expect(resolveSource(candidate, PAGE)).toBeNull()
  })

  it.each([
    'data:application/json,{"score":{"total":9,"possible":9}}',
    'javascript:void 0',
    'blob:http://localhost:3000/abcd',
  ])('refuses a scheme that is not a file or a server: %s', (candidate) => {
    expect(resolveSource(candidate, PAGE)).toBeNull()
  })

  it('refuses a data: URL even from a file:// page', () => {
    // The case the origin check alone cannot catch. `data:` and an opaque
    // `file://` origin are both the string "null", so comparing origins would
    // accept a fabricated report on exactly the deployment the README
    // recommends for reading one off disk.
    const onDisk = 'file:///C:/reports/index.html'
    expect(resolveSource('data:application/json,{}', onDisk)).toBeNull()
  })

  it('still accepts a local file from a file:// page', () => {
    // The documented feature: somebody was handed a report and opened the
    // console next to it. Every `file:` URL shares the opaque origin, and the
    // boundary being defended is a remote one.
    const onDisk = 'file:///C:/reports/index.html'
    expect(resolveSource('./report.json', onDisk)).toBe('file:///C:/reports/report.json')
  })

  it('returns null rather than throwing on nonsense', () => {
    expect(resolveSource('http://[', PAGE)).toBeNull()
    expect(resolveSource(null, PAGE)).toBeNull()
    expect(resolveSource('', PAGE)).toBeNull()
  })
})

describe('sourceOverride', () => {
  it('reads src from the query string', () => {
    expect(sourceOverride('?src=report.json', PAGE)).toBe('http://localhost:3000/report.json')
  })

  it('is null when there is no override', () => {
    expect(sourceOverride('', PAGE)).toBeNull()
    expect(sourceOverride('?other=1', PAGE)).toBeNull()
  })
})

describe('candidatesFor', () => {
  const paths = ['http://127.0.0.1:8642/api/env', './env.json']

  it('is just the paths when no override is given', () => {
    expect(candidatesFor(paths, '', PAGE)).toEqual(paths)
  })

  it('resolves each relative path against the override, and the absolute one is left alone', () => {
    // The latent bug underneath the security one. The override used to be
    // `src.replace(/report\.json$/, '')` used as a candidate URL by itself —
    // so a capability page asking for `env.json` fetched the bare directory,
    // got a listing or a 404, and fell through. The override silently did
    // nothing on every page except the report itself.
    const result = candidatesFor(paths, '?src=/exports/report.json', PAGE)

    expect(result[0]).toBe('http://localhost:3000/exports/env.json')
    expect(result).toContain('http://127.0.0.1:8642/api/env')
    expect(result).toContain('./env.json')
  })

  it('keeps the original paths as fallbacks', () => {
    const result = candidatesFor(paths, '?src=/exports/report.json', PAGE)
    expect(result.slice(-paths.length)).toEqual(paths)
  })

  it('adds nothing when the override is refused', () => {
    expect(candidatesFor(paths, '?src=https://example.invalid/report.json', PAGE)).toEqual(paths)
  })
})

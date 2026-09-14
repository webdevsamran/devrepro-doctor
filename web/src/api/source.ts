/**
 * Where the console is allowed to read a report from.
 *
 * `?src=` exists so somebody handed a sanitized report can open it in the
 * console without running a server — a real feature, and the reason the query
 * parameter is read at all. It was passed straight to `fetch`, which makes the
 * page load and render whatever any URL returns.
 *
 * For most applications that is an SSRF-shaped nuisance. Here it is worse than
 * that, because of what this particular page does with the bytes: it presents
 * them as a reading of *your machine*. A link like
 * `…/#/overview?src=https://example.invalid/clean.json` renders a confident,
 * authoritative, entirely fabricated diagnosis — a green score for a machine
 * nobody looked at. The dashboard plan states the rule this breaks directly:
 * a fake green score is worse than an empty state, because the empty state
 * cannot mislead.
 *
 * So the override is confined to the origin the console was served from. That
 * is not a restriction on the feature: a report you were handed is a file
 * beside the page or under the local server, never a URL on someone else's
 * host.
 *
 * Two details worth stating rather than leaving to be rediscovered:
 *
 * - **The protocol allowlist is not redundant.** `data:` and `javascript:`
 *   URLs have the opaque origin `"null"`, and so does a page opened from
 *   `file://`. Comparing origins alone would let
 *   `?src=data:application/json,{…}` through on exactly the deployment the
 *   README recommends for reading a report off disk.
 * - **Under `file://` every local file shares that opaque origin**, so any
 *   `file:` source is accepted there. That is the documented feature — the
 *   user already opened a local file — and the boundary being defended is a
 *   remote one.
 *
 * The resolved URL is returned rather than the caller's string so that what
 * gets fetched is the thing that was checked, with no second resolution in
 * between that could differ.
 */

/** Schemes a report may be read over. Anything else cannot be a saved file. */
const ALLOWED_PROTOCOLS = new Set(['http:', 'https:', 'file:'])

/**
 * Resolve a `?src=` value against the page, or return `null` to refuse it.
 *
 * `here` is passed in rather than read from `window` so this is a pure
 * function of its arguments and can be tested for the origins it must refuse.
 */
export function resolveSource(raw: string | null, here: string): string | null {
  if (!raw) return null

  let page: URL
  let resolved: URL
  try {
    page = new URL(here)
    resolved = new URL(raw, here)
  } catch {
    // An unparseable override is a typo, not an attack, and either way there
    // is nothing to fetch.
    return null
  }

  if (!ALLOWED_PROTOCOLS.has(resolved.protocol)) return null
  if (resolved.origin !== page.origin) return null
  return resolved.href
}

/** The `?src=` override for the current page, already confined. */
export function sourceOverride(search: string, here: string): string | null {
  return resolveSource(new URLSearchParams(search).get('src'), here)
}

/**
 * Candidate URLs for one dataset, with the override resolved *per path*.
 *
 * The capability pages each load a different file — `profile.json`,
 * `env.json`, `fleet.json` — so a single override URL cannot serve them. The
 * previous code tried to cope by stripping a trailing `report.json` off the
 * override and fetching the bare directory, which returns a listing or a 404
 * for every one of them: the override silently did nothing on every page
 * except the report itself.
 *
 * Resolving each relative path against the override is what that string
 * manipulation was reaching for, and it needs no string manipulation: a URL
 * resolved against `…/report.json` is already relative to the directory
 * holding it. Absolute candidates — the localhost API — are left alone,
 * because they are not relative to anything.
 */
export function candidatesFor(paths: string[], search: string, here: string): string[] {
  const base = sourceOverride(search, here)
  if (!base) return [...paths]

  const overrides: string[] = []
  for (const path of paths) {
    if (/^[a-z][a-z0-9+.-]*:/i.test(path)) continue // already absolute
    const resolved = resolveSource(path, base)
    if (resolved) overrides.push(resolved)
  }
  return [...overrides, ...paths]
}

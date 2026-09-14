/**
 * Escaping a diagnostic value into a Markdown table cell.
 *
 * Three modules built the same row with the same incomplete escape,
 * `text.replace(/\|/g, '\\|')`, and CodeQL flagged all three. The pipe needed
 * escaping; escaping only it is the bug, because the backslash doing the work
 * is itself Markdown syntax.
 *
 * The inputs below are not contrived. This is a Windows-first tool: summaries
 * carry `C:\Users\dev\bin`, remediation hints carry shell fragments with pipes,
 * PATH values carry both, and evidence excerpts carry newlines.
 */
import { describe, expect, it } from 'vitest'

import { escapeTableCell } from '../markdown'

describe('escapeTableCell', () => {
  it('escapes a pipe so it cannot end the cell', () => {
    expect(escapeTableCell('a | b')).toBe('a \\| b')
  })

  it('escapes the backslash before the pipe, not after', () => {
    // The whole defect. `'x\\'.replace(/\|/g, '\\|')` leaves `x\` and then a
    // value ending in a backslash directly before a pipe produces `\\|`, which
    // Markdown reads as an escaped backslash followed by a live cell
    // separator. Escaping the backslashes first makes the pipe's escape the
    // only unescaped backslash in the string.
    expect(escapeTableCell('ends with a backslash\\')).toBe('ends with a backslash\\\\')
    expect(escapeTableCell('trailing\\|piped')).toBe('trailing\\\\\\|piped')
  })

  it('survives a Windows path next to a pipe', () => {
    const summary = 'C:\\Users\\dev\\bin | shadowed'
    const escaped = escapeTableCell(summary)

    // Every backslash from the input is doubled, and the only single backslash
    // left is the one escaping the pipe.
    expect(escaped).toBe('C:\\\\Users\\\\dev\\\\bin \\| shadowed')
    // Unescaping the way a Markdown renderer does returns the original.
    expect(escaped.replace(/\\(.)/g, '$1')).toBe(summary)
  })

  it('does not double-escape on a second pass', () => {
    // Not an invariant the callers rely on, but the failure it guards against
    // is ugly: a value escaped twice renders its own backslashes to the reader.
    const once = escapeTableCell('a | b')
    expect(escapeTableCell(once)).not.toBe(once)
    expect(escapeTableCell(once)).toBe('a \\\\\\| b')
  })

  it('folds a newline into a space', () => {
    // A table row ends at a line break, so a multi-line summary did not break
    // one cell -- it ended the table and left the rest as loose prose.
    expect(escapeTableCell('first line\nsecond line')).toBe('first line second line')
    expect(escapeTableCell('crlf\r\nhere')).toBe('crlf here')
    expect(escapeTableCell('cr\rhere')).toBe('cr here')
  })

  it('leaves ordinary text alone', () => {
    expect(escapeTableCell('node 18.19.0 does not satisfy >=20')).toBe(
      'node 18.19.0 does not satisfy >=20',
    )
  })

  it('handles an empty string', () => {
    expect(escapeTableCell('')).toBe('')
  })

  it('never emits a bare pipe, whatever it is given', () => {
    // The property the three call sites actually depend on: after escaping,
    // no `|` in the output is preceded by an even number of backslashes.
    const nasty = [
      'a|b',
      'a\\|b',
      'a\\\\|b',
      '|',
      '\\',
      '\\\\',
      'C:\\x\\|y',
      'cmd | grep \\ | wc',
    ]
    for (const input of nasty) {
      const escaped = escapeTableCell(input)
      const bare = [...escaped.matchAll(/\|/g)].filter((match) => {
        let backslashes = 0
        for (let i = match.index! - 1; i >= 0 && escaped[i] === '\\'; i -= 1) backslashes += 1
        return backslashes % 2 === 0
      })
      expect(bare, `bare pipe in ${JSON.stringify(escaped)} from ${JSON.stringify(input)}`).toEqual(
        [],
      )
    }
  })
})

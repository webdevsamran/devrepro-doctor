/**
 * Putting arbitrary diagnostic text into a Markdown table cell.
 *
 * Three places built the same row and escaped it the same incomplete way:
 *
 *     text.replace(/\|/g, '\\|')
 *
 * A pipe ends a cell, so escaping it is necessary. Escaping *only* it is the
 * bug, because the backslash doing the escaping is itself Markdown syntax. Feed
 * that expression a value ending in a backslash and it produces `\\|` — which
 * Markdown reads as an escaped backslash followed by an unescaped pipe, and the
 * cell splits anyway. The escaping defeats itself on exactly the input it was
 * added for.
 *
 * That input is not hypothetical here. This is a Windows-first diagnostics
 * tool: summaries carry `C:\Users\dev\bin`, remediation hints carry shell
 * fragments with pipes, and PATH values carry both. A finding about
 * `C:\tools\` next to a piped command is an ordinary row, and it broke the
 * table it was printed into.
 *
 * The order below is the whole fix: backslashes first, then pipes. Reversed, it
 * would escape the backslashes it had just inserted and double them.
 *
 * Newlines are handled for the same reason and were not handled at all. A
 * Markdown table row ends at a line break, so a multi-line summary — evidence
 * excerpts have them — did not merely break a cell, it ended the table and left
 * the remainder as loose prose. Replaced with a space rather than `<br>`
 * because the destination is a GitHub issue, and `<br>` is HTML that reads as
 * literal text anywhere Markdown is rendered without it.
 */

/**
 * Escape one value for a Markdown table cell.
 *
 * Order matters, and a test pins it.
 */
export function escapeTableCell(text: string): string {
  return text
    .replace(/\\/g, '\\\\')
    .replace(/\|/g, '\\|')
    .replace(/\r?\n|\r/g, ' ')
    .trim()
}

/**
 * The navigation model: one source of truth for the sidebar, the router and
 * the command palette.
 *
 * The previous shell rendered 32 links as a single flat wrapping row in the
 * header. At that count a flat list stops being navigation and becomes a wall
 * — nothing groups, nothing is findable, and the active item is one blue word
 * among thirty-two. Six groups plus a palette replaces scanning with jumping.
 */

export type NavItem = {
  /** Route path, without the leading slash. Also the hash URL. */
  id: string
  label: string
  /** Shown in the collapsed sidebar and the palette. */
  icon: string
  /** Extra words the palette should match on, beyond the label. */
  keywords?: string
}

export type NavGroup = {
  title: string
  items: NavItem[]
}

export const NAV_GROUPS: NavGroup[] = [
  {
    title: 'Overview',
    items: [
      { id: 'home', label: 'Home', icon: '◈', keywords: 'start welcome' },
      { id: 'overview', label: 'Machine Overview', icon: '▤', keywords: 'summary os cpu ram disk' },
      { id: 'readiness', label: 'Project Readiness', icon: '◎', keywords: 'requirements build' },
      { id: 'profile', label: 'Profile & Maturity', icon: '◍', keywords: 'score reproducibility' },
    ],
  },
  {
    title: 'Environment',
    items: [
      { id: 'toolchains', label: 'Toolchains', icon: '⚒', keywords: 'versions tools installed node python' },
      { id: 'path', label: 'PATH Explorer', icon: '⇉', keywords: 'shadowing precedence duplicates which' },
      { id: 'envvars', label: 'Env Vars', icon: '⌗', keywords: 'environment variables dotenv' },
      { id: 'services', label: 'Ports & Services', icon: '⇋', keywords: 'ports conflicts listening' },
      { id: 'githealth', label: 'Git Health', icon: '⑂', keywords: 'git lfs submodule worktree' },
      { id: 'network', label: 'Network & TLS', icon: '☁', keywords: 'proxy certificate dns registry' },
      { id: 'shellstartup', label: 'Shell Startup', icon: '❯', keywords: 'profile bashrc zshrc slow' },
    ],
  },
  {
    title: 'Platform',
    items: [
      { id: 'containers', label: 'Containers & WSL', icon: '▣', keywords: 'docker podman wsl daemon' },
      { id: 'gpustack', label: 'GPU / AI Stack', icon: '◲', keywords: 'cuda rocm nvidia driver metal' },
    ],
  },
  {
    title: 'Diagnose',
    items: [
      { id: 'findings', label: 'Findings', icon: '⚑', keywords: 'issues problems errors warnings triage' },
      { id: 'rules', label: 'Rules', icon: '☰', keywords: 'packs checks catalogue' },
      { id: 'remediation', label: 'Remediation Plan', icon: '✎', keywords: 'fix repair plan safe' },
      { id: 'generatedenv', label: 'Generated Env', icon: '⎘', keywords: 'devcontainer mise asdf draft' },
    ],
  },
  {
    title: 'Reproduce',
    items: [
      { id: 'snapshots', label: 'Snapshots', icon: '⧉', keywords: 'manifest export share' },
      { id: 'diff', label: 'Environment Diff', icon: '⇄', keywords: 'compare works on my machine' },
      { id: 'drifttimeline', label: 'Drift Timeline', icon: '⌁', keywords: 'history changes over time' },
      { id: 'baseline', label: 'Baseline', icon: '▦', keywords: 'approved expected manifest' },
      { id: 'history', label: 'History', icon: '⟲', keywords: 'previous scans' },
    ],
  },
  {
    title: 'Fleet',
    items: [
      { id: 'fleet', label: 'Fleet Dashboard', icon: '⌸', keywords: 'team machines aggregate' },
      { id: 'agents', label: 'Agents & Enrollment', icon: '⌬', keywords: 'enroll token machine' },
      { id: 'exceptions', label: 'Exceptions', icon: '⊘', keywords: 'waiver expiry review' },
      { id: 'auditlog', label: 'Audit Log', icon: '⎙', keywords: 'events immutable' },
      { id: 'retention', label: 'Retention', icon: '⌛', keywords: 'purge policy' },
      { id: 'serversettings', label: 'Server Settings', icon: '⚙', keywords: 'configuration' },
      { id: 'plugins', label: 'Plugins', icon: '⊞', keywords: 'extensions entry points' },
    ],
  },
  {
    title: 'About',
    items: [
      { id: 'docs', label: 'Docs', icon: '◫', keywords: 'documentation help' },
      { id: 'contributors', label: 'Contributors', icon: '☺', keywords: 'authors credits' },
      { id: 'about', label: 'About', icon: 'ⓘ', keywords: 'version license privacy' },
    ],
  },
]

export const ALL_ITEMS: NavItem[] = NAV_GROUPS.flatMap((g) => g.items)

export const GROUP_OF: Record<string, string> = Object.fromEntries(
  NAV_GROUPS.flatMap((g) => g.items.map((i) => [i.id, g.title])),
)

export function itemById(id: string): NavItem | undefined {
  return ALL_ITEMS.find((i) => i.id === id)
}

/**
 * Rank nav items against a query.
 *
 * A prefix match on the label beats a word-boundary match, which beats a
 * substring, which beats a keyword hit — so typing "path" puts "PATH Explorer"
 * first rather than whatever happens to contain the letters earliest.
 */
export function searchItems(query: string): NavItem[] {
  const q = query.trim().toLowerCase()
  if (!q) return ALL_ITEMS
  const scored: Array<{ item: NavItem; score: number }> = []
  for (const item of ALL_ITEMS) {
    const label = item.label.toLowerCase()
    const words = label.split(/\s+/)
    let score = 0
    if (label.startsWith(q)) score = 100
    else if (words.some((w) => w.startsWith(q))) score = 80
    else if (label.includes(q)) score = 60
    else if ((item.keywords ?? '').includes(q)) score = 40
    else if (GROUP_OF[item.id].toLowerCase().includes(q)) score = 20
    if (score > 0) scored.push({ item, score })
  }
  return scored.sort((a, b) => b.score - a.score || a.item.label.localeCompare(b.item.label))
    .map((s) => s.item)
}

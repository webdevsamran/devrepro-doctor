'use strict';

/**
 * A readiness badge on a GitHub repository page.
 *
 * The obvious implementation is the one this does not do: fetch a score from a
 * service, for every repository the user visits. That would mean an endpoint,
 * and it would mean sending this project a log of somebody's browsing.
 *
 * So the data is local. The user pastes the output of `devrepro agent-check
 * --badge` for repositories they care about, in the options page, and this
 * renders what they already have. The extension makes **no network requests at
 * all** -- there is no `fetch` in this file, and the manifest asks for no
 * permission that would allow one.
 *
 * That is a smaller feature than a hosted badge and it is the honest version:
 * a browser extension that phones home about every page you visit is exactly
 * the shape this project exists to be the opposite of.
 */

const COLOURS = {
  brightgreen: '#1a7f37',
  yellow: '#9a6700',
  orange: '#bc4c00',
  red: '#cf222e',
  lightgrey: '#6e7781',
};

/** `owner/repo` from the current path, or null when this is not a repo page. */
function repoSlug() {
  const parts = window.location.pathname.split('/').filter(Boolean);
  if (parts.length < 2) return null;
  // Reserved first segments that look like an owner and are not.
  if (['settings', 'notifications', 'explore', 'marketplace', 'sponsors'].includes(parts[0])) {
    return null;
  }
  return `${parts[0]}/${parts[1]}`;
}

function render(badge) {
  if (document.querySelector('.devrepro-badge')) return;

  // Beside the repository name rather than injected into the README: the README
  // is somebody else's content, and an extension editing it is an extension
  // that shows people things the page does not say.
  const anchor = document.querySelector('[itemprop="name"]')?.parentElement;
  if (!anchor) return;

  const element = document.createElement('span');
  element.className = 'devrepro-badge';
  element.textContent = `${badge.label}: ${badge.message}`;
  element.title =
    'From a badge payload you saved locally. This extension makes no network requests.';
  Object.assign(element.style, {
    display: 'inline-block',
    marginLeft: '8px',
    padding: '2px 8px',
    borderRadius: '12px',
    fontSize: '12px',
    fontWeight: '500',
    color: '#ffffff',
    backgroundColor: COLOURS[badge.color] || COLOURS.lightgrey,
  });
  anchor.appendChild(element);
}

const slug = repoSlug();
if (slug) {
  chrome.storage.local.get(['badges'], (stored) => {
    const badge = (stored.badges || {})[slug];
    if (badge) render(badge);
  });
}

'use strict';

/** Storage is `{ badges: { "owner/repo": <shields payload> } }`. */
function refresh() {
  chrome.storage.local.get(['badges'], (stored) => {
    const list = document.getElementById('list');
    list.textContent = '';
    for (const [slug, badge] of Object.entries(stored.badges || {})) {
      const item = document.createElement('li');
      item.textContent = `${slug} — ${badge.message}`;
      const remove = document.createElement('button');
      remove.textContent = 'Remove';
      remove.style.marginLeft = '8px';
      remove.addEventListener('click', () => {
        const badges = { ...(stored.badges || {}) };
        delete badges[slug];
        chrome.storage.local.set({ badges }, refresh);
      });
      item.appendChild(remove);
      list.appendChild(item);
    }
  });
}

document.getElementById('save').addEventListener('click', () => {
  const slug = document.getElementById('slug').value.trim();
  const raw = document.getElementById('badge').value.trim();
  const status = document.getElementById('status');

  if (!/^[\w.-]+\/[\w.-]+$/.test(slug)) {
    status.textContent = 'Expected owner/repo.';
    return;
  }
  let badge;
  try {
    badge = JSON.parse(raw);
  } catch {
    status.textContent = 'That is not JSON. Paste the output of `devrepro agent-check --badge`.';
    return;
  }
  if (badge.schemaVersion !== 1 || !badge.message) {
    // Checked rather than accepted: a malformed badge renders as an empty pill
    // on a page the user does not control, and looks like the extension is
    // broken rather than the input.
    status.textContent = 'That is not a shields endpoint payload.';
    return;
  }

  chrome.storage.local.get(['badges'], (stored) => {
    const badges = { ...(stored.badges || {}), [slug]: badge };
    chrome.storage.local.set({ badges }, () => {
      status.textContent = 'Saved.';
      refresh();
    });
  });
});

refresh();

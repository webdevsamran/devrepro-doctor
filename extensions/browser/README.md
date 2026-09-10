# DevRepro readiness (browser extension)

Shows a repository's agent-readiness badge on its GitHub page.

Load it unpacked: `chrome://extensions` → Developer mode → *Load unpacked* →
this folder. There is no build step and no dependencies.

## It makes no network requests

The obvious implementation fetches a score from a service, for every repository
you visit — which means an endpoint, and a log of your browsing arriving at
somebody's server. This project exists to be the opposite of that shape, so the
data is local: paste the output of `devrepro agent-check --badge` for the
repositories you care about, in the options page, and the extension renders
what you already have.

There is no `fetch` in the source, and the manifest asks for no permission that
would allow one. `storage` and `github.com` are the whole list.

The badge is drawn beside the repository name, not injected into the README —
the README is somebody else's content, and an extension that edits it is an
extension that shows you things the page does not say.

## The trade

This is a smaller feature than a hosted badge: you have to save each repository
yourself. That is the honest version. A browser extension that phones home about
every page you visit is not a thing this project is going to ship in order to
save somebody four keystrokes.

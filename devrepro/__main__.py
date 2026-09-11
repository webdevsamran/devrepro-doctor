"""Allow ``python -m devrepro`` to invoke the CLI.

Through ``main()``, not through ``app()``. This file used to call the Typer
application directly, which meant the two entry points were not the same
program:

* ``_make_output_encoding_non_fatal()`` never ran, so the Windows console
  encoding fix -- shipped because a single U+2192 in a remediation hint ended
  ``devrepro check`` in a ``UnicodeEncodeError`` -- applied only to the
  installed script.
* An unhandled exception reached the interpreter and exited 1, which this
  project publishes as READY_WITH_WARNINGS, instead of ``INTERNAL_ERROR``.

And ``python -m devrepro`` is the form this repository's own documentation uses
throughout -- AGENTS.md, the verification steps, every reproduction in the
changelog -- because it works without the package being installed. The entry
point people actually type was the one without the error handling.
"""

from __future__ import annotations

from devrepro.cli.app import main

if __name__ == "__main__":
    main()

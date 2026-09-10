# DevRepro Doctor in JetBrains IDEs

**This is External Tools configuration, not a plugin.** That is a deliberate
choice and worth the paragraph.

A JetBrains plugin is a Kotlin/Gradle project, a `plugin.xml`, a compatibility
range against IntelliJ platform builds, a Marketplace listing and a signing key
— and it would be maintained by a project that ships no compiled artefacts
anywhere else. External Tools are XML files that work in every JetBrains IDE
today, on the version already installed, and they cover what a plugin would
actually be doing: run the command, show the output, jump to the file.

If somebody wants the deeper integration a plugin buys — inline inspections,
gutter icons — that is worth building when there is somebody asking. There is
not yet, and a half-maintained plugin in the Marketplace is worse than none.

## Install

Copy `tools/DevRepro.xml` into your IDE configuration directory:

| OS | Path |
|---|---|
| macOS | `~/Library/Application Support/JetBrains/<IDE><version>/tools/` |
| Linux | `~/.config/JetBrains/<IDE><version>/tools/` |
| Windows | `%APPDATA%\JetBrains\<IDE><version>\tools\` |

Restart the IDE. The commands appear under **Tools → External Tools →
DevRepro**.

Or add them by hand: *Settings → Tools → External Tools → +*, with the program,
arguments and working directory from the XML.

## What you get

| Tool | Command |
|---|---|
| Scan this machine | `devrepro doctor` |
| Check the environment contract | `devrepro guard --scope changed` |
| Agent readiness | `devrepro agent-check .` |
| Explain a rule id | `devrepro explain $Prompt$` |

The output filter on the scan turns `prefix/name` rule ids into clickable
entries where a file is involved.

--8<-- "INTEROP.md"

## Where this stops and something else starts

**Application profiling — [react-doctor](https://github.com/millionco/react-doctor).**
This tool explains why an application will not build on a given machine. Why it
is *slow once it does* is a different question, answered by attaching to a
running process — and attaching a debugger to somebody's process is the
furthest thing from read-only in this project. react-doctor does that job well;
this one links there rather than competing.

**Environment management — [Nix](https://nixos.org),
[mise](https://mise.jdx.dev), [Devbox](https://www.jetify.com/devbox).**
They manage environments; this diagnoses them, including theirs. `devrepro
envmanagers` reports what each declares versus what is actually active, and
`devrepro reproduce --emit nix` hands a Nix-shaped team a starting point rather
than pretending to be a package manager.

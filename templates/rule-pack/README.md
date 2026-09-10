# devrepro rule-pack template

Copy this directory, rename `devrepro_rulepack_example`, and you have a working
rule pack.

A template rather than a cookiecutter, because a cookiecutter is a dependency
and a build step for something `cp -r` and one find-and-replace already do --
and a template you can read start to finish teaches the contract better than a
generator that hides it.

```bash
cp -r templates/rule-pack ../my-devrepro-pack
cd ../my-devrepro-pack
# rename the package directory and the references to it in pyproject.toml
pip install -e .
devrepro rules-test devrepro_rulepack_example
devrepro doctor      # your pack now runs as part of every scan
```

## What a rule pack is

A function that receives the machine's state and returns findings. It does not
run commands, write files or open sockets. `devrepro rules-test` checks that
**statically**, because a pack that only writes under some condition passes a
runtime check on every machine except the one it fails on.

## The four things that make one wrong

| Problem | What it does to a user |
|---|---|
| A finding with no evidence | The model refuses to build it, so it surfaces as an exception at scan time -- in somebody else's CI |
| A rule id under a built-in prefix | `devrepro explain` describes somebody else's rule, and nobody can tell which pack produced the finding |
| Any side effect | Breaks the read-only guarantee the whole tool rests on |
| An uncaught exception | Becomes a `rulepack/<name>/failed` finding, so you never see your own crash |

## Publishing

Nothing needs to be registered anywhere. The entry point in `pyproject.toml` is
the whole mechanism: install the package and `devrepro plugins` lists it.

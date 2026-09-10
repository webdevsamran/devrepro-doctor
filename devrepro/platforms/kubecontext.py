"""Which cluster `kubectl` is pointed at, which is a blast-radius question.

The local-Kubernetes half of this is easy: kind, minikube, k3d, Docker
Desktop and Rancher Desktop all name their contexts predictably, and knowing
which of them is running tells you whether `kubectl apply` will reach a cluster
at all.

The half that matters is the other one. `kubectl` has exactly one current
context, it is global to the user, it persists across shells and reboots, and
nothing in a terminal prompt shows it unless somebody installed a plugin to put
it there. Every `kubectl delete` a person has ever regretted was typed into a
shell whose context they believed was something else.

That is the same question `devrepro agent-check` asks about writable paths and
credential-shaped variables, and it belongs beside them: before an agent -- or a
tired person -- runs a command here, what could it reach?

**Read from the kubeconfig, never from a cluster.** `kubectl config
current-context` and `kubectl config get-contexts` parse a local file and make
no connection. `kubectl cluster-info` would contact the API server, which is a
network side effect and, on a production cluster, an authenticated one that
appears in an audit log. Naming the cluster is enough to answer the question
worth asking.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = [
    "LOCAL_CONTEXT_MARKERS",
    "PRODUCTION_MARKERS",
    "KubeContext",
    "classify_context",
    "parse_contexts",
]

#: Context-name fragments that mean a cluster on this machine. Matched as
#: substrings, case-insensitively, because every tool prefixes differently.
LOCAL_CONTEXT_MARKERS: tuple[str, ...] = (
    "kind-",
    "minikube",
    "k3d-",
    "docker-desktop",
    "docker-for-desktop",
    "rancher-desktop",
    "colima",
    "orbstack",
    "microk8s",
)

#: Fragments that suggest a context is not a toy. Deliberately a *suggestion*:
#: naming conventions vary, and this reports a possibility rather than a fact.
#: A false positive costs a person two seconds of reading; a false negative
#: costs whatever was in the cluster.
PRODUCTION_MARKERS: tuple[str, ...] = (
    "prod",
    "production",
    "live",
    "main-cluster",
    "primary",
)


@dataclass(frozen=True)
class KubeContext:
    """One context from the kubeconfig, and what it appears to point at."""

    name: str
    cluster: str = ""
    namespace: str = ""
    current: bool = False

    @property
    def is_local(self) -> bool:
        lowered = f"{self.name} {self.cluster}".lower()
        return any(marker in lowered for marker in LOCAL_CONTEXT_MARKERS)

    @property
    def looks_production(self) -> bool:
        """Whether the *name* suggests production.

        Name-based, and it says so. A cluster's actual criticality is not
        knowable from a kubeconfig, and the alternative -- contacting the API
        server to look -- is a network call against a production cluster from a
        diagnostic command, which is not a trade worth making.
        """
        if self.is_local:
            return False
        lowered = f"{self.name} {self.cluster} {self.namespace}".lower()
        return any(marker in lowered for marker in PRODUCTION_MARKERS)


_ROW = re.compile(r"^(?P<current>\*?)\s*(?P<rest>\S.*)$")


def parse_contexts(text: str) -> tuple[KubeContext, ...]:
    """Read `kubectl config get-contexts` table output.

    Column-count tolerant. The table has five columns and the last two are
    routinely empty, so splitting on whitespace yields three, four or five
    fields per row depending on the entry -- and a parser assuming five silently
    returns nothing for exactly the rows with no namespace set.
    """
    contexts: list[KubeContext] = []
    for line in (text or "").splitlines():
        if not line.strip() or line.lstrip().startswith("CURRENT"):
            continue
        match = _ROW.match(line)
        if not match:
            continue
        fields = match.group("rest").split()
        if not fields:
            continue
        contexts.append(
            KubeContext(
                name=fields[0],
                cluster=fields[1] if len(fields) > 1 else "",
                namespace=fields[3] if len(fields) > 3 else "",
                current=bool(match.group("current")),
            )
        )
    return tuple(contexts)


@dataclass(frozen=True)
class ContextVerdict:
    """What the current context is, and whether it is worth saying out loud."""

    current: KubeContext | None
    local_available: tuple[str, ...] = ()
    warn: bool = False
    detail: str = ""


def classify_context(
    contexts: tuple[KubeContext, ...],
    *,
    local_tools: tuple[str, ...] = (),
) -> ContextVerdict:
    """The current context, and whether pointing at it deserves a warning.

    Silent when the current context is local, which is the common and correct
    case. A warning on every developer's kind cluster is a warning nobody
    reads by the second week.
    """
    current = next((c for c in contexts if c.current), None)
    if current is None:
        return ContextVerdict(
            current=None,
            local_available=local_tools,
            detail="kubectl has no current context set.",
        )

    if current.looks_production:
        return ContextVerdict(
            current=current,
            local_available=local_tools,
            warn=True,
            detail=(
                f"kubectl's current context is {current.name!r}, whose name suggests a "
                "production cluster. The context is global to your user and persists "
                "across shells and reboots, and nothing in a normal prompt shows it."
            ),
        )

    if not current.is_local:
        return ContextVerdict(
            current=current,
            local_available=local_tools,
            detail=(
                f"kubectl's current context is {current.name!r}, which is not a local "
                "cluster this machine runs."
            ),
        )

    return ContextVerdict(
        current=current,
        local_available=local_tools,
        detail=f"kubectl points at the local cluster {current.name!r}.",
    )

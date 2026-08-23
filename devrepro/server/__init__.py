"""Self-hosted team/enterprise fleet service (optional module).

Local-first remains the default: this server is only needed when teams want
centralized snapshots, baselines, policy, audit and drift dashboards.
"""

from devrepro.server.api import create_app
from devrepro.server.db import ServerDB

__all__ = ["ServerDB", "create_app"]

"""Mneme tooling shared with the Agent's scripts namespace."""

from pkgutil import extend_path

# Both the repository and python-agent expose scripts. Keep both discoverable
# when tests import host tooling and Agent contract exporters in one process.
__path__ = extend_path(__path__, __name__)

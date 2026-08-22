#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
exec python3 -m scripts.workspace.bootstrap --update --report .workspace-report.json "$@"

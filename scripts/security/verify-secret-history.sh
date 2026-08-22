#!/usr/bin/env sh
set -eu

image=${1:-zricethezav/gitleaks@sha256:c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f}
repository=${2:-$(git rev-parse --show-toplevel)}
repository=$(cd "$repository" && pwd -P)
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
config="$script_dir/gitleaks.toml"
report=$(mktemp)
trap 'rm -f "$report"' EXIT INT TERM

if [ ! -f "$config" ] || [ -L "$config" ]; then
    echo "secret history scan failed closed: reviewed Gitleaks config is missing or a symlink" >&2
    exit 1
fi

if ! docker run --rm \
        --volume "$repository:/repository:ro" \
        --volume "$config:/gitleaks.toml:ro" \
        --workdir /repository \
        --entrypoint sh \
        "$image" \
        -c 'set -eu
            git config --global --add safe.directory /repository
            shallow=$(git rev-parse --is-shallow-repository)
            test "$shallow" = false || {
                echo "secret history scan failed closed: shallow Git history" >&2
                exit 1
            }
            commit_count=$(git rev-list --count --all)
            test "$commit_count" -gt 0
            gitleaks git --no-banner --redact --exit-code 1 --config /gitleaks.toml /repository' \
        >"$report" 2>&1; then
    cat "$report"
    exit 1
fi

cat "$report"
if ! grep -E '[1-9][0-9]* commits scanned' "$report" >/dev/null; then
    echo "secret history scan failed closed: no non-zero commit evidence" >&2
    exit 1
fi

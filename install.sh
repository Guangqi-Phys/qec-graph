#!/bin/sh
set -eu

die() {
    printf 'qec-graph installer: %s\n' "$1" >&2
    exit 1
}

repository=Guangqi-Phys/qec-graph
version="${1:-v0.4.0rc1}"
case "$version" in
    *[!A-Za-z0-9._-]*) die 'invalid release tag' ;;
    v[0-9]*) ;;
    *) die 'invalid release tag' ;;
esac

case "$(uname -s)-$(uname -m)" in
    Darwin-arm64) asset=qec-graph-darwin-arm64 ;;
    Darwin-x86_64) asset=qec-graph-darwin-x86_64 ;;
    *) die 'this release supports Apple Silicon and Intel Macs' ;;
esac

command -v gh >/dev/null 2>&1 || die 'install GitHub CLI and sign in with gh auth login'
bin_dir="${QECGRAPH_BIN_DIR:-$HOME/.local/bin}"
case "$bin_dir" in /*) ;; *) die 'QECGRAPH_BIN_DIR must be an absolute path' ;; esac
destination="$bin_dir/qec-graph"
[ ! -d "$destination" ] || die "installation path is a directory: $destination"

download="$(mktemp -d "${TMPDIR:-/tmp}/qec-graph-install.XXXXXX")"
staged=''
cleanup() {
    if [ -n "$staged" ]; then rm -f "$staged"; fi
    rm -rf "$download"
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM

gh release download "$version" --repo "$repository" --dir "$download" \
    --pattern "$asset" --pattern "$asset.sha256" \
    || die "could not download $version. Check gh auth status and repository access"

IFS=' ' read -r expected filename < "$download/$asset.sha256" || die 'invalid SHA-256 manifest'
case "$expected" in ''|*[!0-9a-f]*) die 'invalid SHA-256 manifest' ;; esac
[ "${#expected}" -eq 64 ] && [ "$filename" = "$asset" ] || die 'invalid SHA-256 manifest'
actual="$(shasum -a 256 "$download/$asset")"
[ "${actual%% *}" = "$expected" ] || die 'download failed SHA-256 verification'

mkdir -p "$bin_dir"
staged="$(mktemp "$bin_dir/.qec-graph.XXXXXX")"
install -m 755 "$download/$asset" "$staged"
"$staged" --help >/dev/null || die 'the executable could not start on this Mac'
mv -f "$staged" "$destination"
staged=''
printf 'Installed qec-graph %s at %s\n' "$version" "$destination"

case ":${PATH:-}:" in
    *":$bin_dir:"*) ;;
    *)
        startup=''
        if [ "$bin_dir" = "$HOME/.local/bin" ]; then
            case "${SHELL:-/bin/zsh}" in
                */zsh) startup="${ZDOTDIR:-$HOME}/.zshrc" ;;
                */bash) startup="$HOME/.bash_profile" ;;
            esac
        fi
        path_line='export PATH="$HOME/.local/bin:$PATH" # qec-graph installer'
        if [ -n "$startup" ] && (
            grep -Fqx "$path_line" "$startup" 2>/dev/null ||
                printf '\n%s\n' "$path_line" >> "$startup"
        ); then
            printf 'Open a new terminal to use qec-graph on PATH.\n'
        else
            printf 'Add %s to PATH or run %s directly.\n' "$bin_dir" "$destination"
        fi
        ;;
esac

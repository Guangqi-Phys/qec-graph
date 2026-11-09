#!/bin/sh
set -eu

die() {
    printf 'qec-graph installer: %s\n' "$1" >&2
    exit 1
}

repository=Guangqi-Phys/qec-graph
releases_url="https://github.com/$repository/releases"

platform="$(uname -s)"
case "$platform-$(uname -m)" in
    Darwin-arm64) asset=qec-graph-darwin-arm64 ;;
    Darwin-x86_64) asset=qec-graph-darwin-x86_64 ;;
    Linux-aarch64|Linux-arm64) asset=qec-graph-linux-arm64 ;;
    Linux-x86_64) asset=qec-graph-linux-x86_64 ;;
    *) die 'supported platforms are macOS and Linux on arm64 or x86_64' ;;
esac

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

version="${1:-}"
if [ -z "$version" ]; then
    latest="$(curl -sSL --proto '=https' --proto-redir '=https' --retry 2 \
        --output /dev/null --write-out '%{http_code} %{url_effective}' "$releases_url/latest")" \
        || die 'could not resolve the latest GitHub Release'
    case "$latest" in
        "200 $releases_url/tag/"*) release_page="${latest#200 }" ;;
        "200 $releases_url"|"200 $releases_url/"|"404 $releases_url/latest")
            curl -fsSL --proto '=https' --proto-redir '=https' --retry 2 \
                --output "$download/releases.atom" "$releases_url.atom" \
                || die 'could not download the GitHub Releases feed'
            release_page="$(awk '
                /<entry>/ { in_entry = 1 }
                /<\/entry>/ && in_entry { exit }
                in_entry && /<link[[:space:]]/ && /rel="alternate"/ && match($0, /href="[^"]*"/) {
                    print substr($0, RSTART + 6, RLENGTH - 7)
                    exit
                }
            ' "$download/releases.atom")" || die 'could not read the GitHub Releases feed'
            ;;
        *) die 'could not resolve the latest GitHub Release' ;;
    esac
    case "$release_page" in
        "$releases_url/tag/"*) version="${release_page#"$releases_url/tag/"}" ;;
        *) die 'no published GitHub Release found' ;;
    esac
fi

case "$version" in
    *[!A-Za-z0-9._-]*) die 'invalid release tag' ;;
    v[0-9]*) ;;
    *) die 'invalid release tag' ;;
esac

release_url="$releases_url/download/$version"
for file in "$asset.sha256" "$asset"; do
    curl -fsSL --proto '=https' --proto-redir '=https' --retry 2 \
        --output "$download/$file" "$release_url/$file" \
        || die "could not download $file for $version"
done

IFS=' ' read -r expected filename < "$download/$asset.sha256" || die 'invalid SHA-256 manifest'
case "$expected" in ''|*[!0-9a-f]*) die 'invalid SHA-256 manifest' ;; esac
[ "${#expected}" -eq 64 ] && [ "$filename" = "$asset" ] || die 'invalid SHA-256 manifest'
case "$platform" in
    Darwin) actual="$(shasum -a 256 "$download/$asset")" ;;
    Linux) actual="$(sha256sum "$download/$asset")" ;;
esac
[ "${actual%% *}" = "$expected" ] || die 'download failed SHA-256 verification'

mkdir -p "$bin_dir"
staged="$(mktemp "$bin_dir/.qec-graph.XXXXXX")"
install -m 755 "$download/$asset" "$staged"
"$staged" --help >/dev/null || die 'the executable could not start on this system'
mv -f "$staged" "$destination"
staged=''
printf 'Installed qec-graph %s at %s\n' "$version" "$destination"

case ":${PATH:-}:" in
    *":$bin_dir:"*) ;;
    *)
        startup=''
        if [ "$bin_dir" = "$HOME/.local/bin" ]; then
            case "$platform:${SHELL:-}" in
                Darwin:|*:*/zsh) startup="${ZDOTDIR:-$HOME}/.zshrc" ;;
                Darwin:*/bash) startup="$HOME/.bash_profile" ;;
                Linux:*/bash) startup="$HOME/.bashrc" ;;
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

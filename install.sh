#!/bin/bash
# Installs ex: the command, the Finder Quick Action, and the Ex.app archiver.
#
#   ./install.sh              install or update
#   ./install.sh --uninstall  remove everything this script added
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMMAND_LINK="/opt/homebrew/bin/ex-extract"
ENGINE_LINK="/opt/homebrew/bin/ex-engine"
SERVICE_DIR="$HOME/Library/Services/Extract Here.workflow"
APP_DIR="$HOME/Applications/Ex.app"
ZSHRC="$HOME/.zshrc"
LSREGISTER="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
PBS="/System/Library/CoreServices/pbs"

# `ex` is taken by /usr/bin/ex, which scripts may call. An alias only affects
# interactive shells, so the command keeps a unique name on PATH.
ALIAS_MARKER="# ex-extract-alias"
ALIAS_LINE="alias ex='ex-extract'  $ALIAS_MARKER"

install_dependencies() {
  local missing=()
  command -v 7zz >/dev/null || missing+=(sevenzip)
  command -v unar >/dev/null || missing+=(unar)
  if ((${#missing[@]})); then
    brew install "${missing[@]}"
  fi
}

install_command() {
  chmod +x "$PROJECT_DIR/bin/ex-extract" "$PROJECT_DIR/bin/ex-engine"
  ln -sf "$PROJECT_DIR/bin/ex-extract" "$COMMAND_LINK"
  ln -sf "$PROJECT_DIR/bin/ex-engine" "$ENGINE_LINK"
}

install_alias() {
  if ! grep -qF "$ALIAS_MARKER" "$ZSHRC" 2>/dev/null; then
    printf '\n%s\n' "$ALIAS_LINE" >>"$ZSHRC"
  fi
}

remove_alias() {
  [ -f "$ZSHRC" ] || return 0
  local filtered
  filtered="$(mktemp)"
  grep -vF "$ALIAS_MARKER" "$ZSHRC" >"$filtered" || true
  # cat rather than mv, so a symlinked dotfile stays a symlink.
  cat "$filtered" >"$ZSHRC"
  rm -f "$filtered"
}

install_service() {
  mkdir -p "$(dirname "$SERVICE_DIR")"
  rm -rf "$SERVICE_DIR"
  cp -R "$PROJECT_DIR/integration/Extract Here.workflow" "$SERVICE_DIR"
  "$PBS" -update
}

install_app() {
  local build
  build="$(mktemp -d)"
  "$PROJECT_DIR/app/build.sh" release "$build" >/dev/null
  mkdir -p "$(dirname "$APP_DIR")"
  rm -rf "$APP_DIR"
  mv "$build/Ex.app" "$APP_DIR"
  rmdir "$build"
  "$LSREGISTER" -f "$APP_DIR"
}

uninstall() {
  rm -f "$COMMAND_LINK" "$ENGINE_LINK"
  remove_alias
  rm -rf "$SERVICE_DIR"
  "$PBS" -update
  if [ -d "$APP_DIR" ]; then
    "$LSREGISTER" -u "$APP_DIR" || true
    rm -rf "$APP_DIR"
  fi
  echo "ex has been uninstalled."
}

main() {
  if [ "${1:-}" = "--uninstall" ]; then
    uninstall
    return
  fi
  install_dependencies
  install_command
  install_alias
  install_service
  install_app
  echo "ex is installed. Open a new terminal (or: source ~/.zshrc) to use the 'ex' command."
}

main "$@"

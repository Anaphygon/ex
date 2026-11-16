#!/bin/sh
# Command Line Tools ship the Swift Testing macro plugin in a subfolder that
# swift build does not search, so point the compiler at it explicitly.
PLUGINS=/Library/Developer/CommandLineTools/usr/lib/swift/host/plugins/testing
. "$(dirname "$0")/build-env.sh"
exec swift test -Xswiftc -plugin-path -Xswiftc "$PLUGINS" "$@"

#!/bin/sh
# Prints only compiler errors (deduplicated) from a swift build/test run.
"$@" 2>&1 | sed -E 's/\x1b\[[0-9;]*m//g' | grep -E '(error|warning): ' | grep -v '^Failed frontend' | sort -u | head -40

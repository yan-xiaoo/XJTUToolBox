#!/bin/bash
# Keep a generated PKGBUILD/.SRCINFO, then put this clone on origin/master.
#
# aur.archlinux.org sometimes advertises HEAD as a commit that is not
# refs/heads/master (two publishes racing each other will do that). git clone
# then stops in detached HEAD, and `git push <remote> master` fails with
# "src refspec master does not match any" because no local master exists.
set -eu

stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
cp -a PKGBUILD .SRCINFO "$stage/"
git checkout -f -B master origin/master
cp -a "$stage/PKGBUILD" "$stage/.SRCINFO" .

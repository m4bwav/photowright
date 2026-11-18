#!/bin/sh
# photowright wiki examples, run against the v0.25.0 tag in a fresh folder.
S=$(dirname "$0"); cd "$S"; rm -rf w; mkdir w; cp rel/tests/fixtures/dark-photo.jpg rel/tests/fixtures/logo.png rel/tests/fixtures/poster.psd w/; cd w
phw() { python ../rel/scripts/phw.py "$@"; }
c() { echo "=== $*"; phw "$@" 2>&1; echo "[exit $?]"; }
c --version
c inspect dark-photo.jpg
c adjust dark-photo.jpg --exposure 1 -o bright.jpg --recipe edit.json
c crop bright.jpg --aspect 1:1 -o square.jpg --recipe edit.json
c adjust dark-photo.jpg --exposure 1 -o bright.jpg
c run edit.json -o replay.jpg
c diff square.jpg replay.jpg
c cutout logo.png --method key -o logo-cut.png
c trace logo.png --kind logo -o logo.svg
c vcheck logo.svg --source logo.png --kind logo
c export logo.svg --format dxf --units mm --drop ffffff -o logo.dxf
c open poster.psd
c sheet dark-photo.jpg bright.jpg --labels before,after -o sheet.png
mkdir photos; cp dark-photo.jpg photos/a.jpg; cp dark-photo.jpg photos/b.jpg
c batch edit.json photos
c batch edit.json photos --apply
c --rung-max 1 cutout logo.png -o rung1.png
c explain screen

#!/usr/bin/env sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "Usage: $0 /path/to/CELL.000" >&2
  exit 2
fi

ogrinfo --formats | grep -q 'S-57' || {
  echo "The installed GDAL does not expose the S-57 driver." >&2
  exit 1
}

ogrinfo -ro -so -al -json "$1"


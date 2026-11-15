#!/usr/bin/env bash
# Rasterise the Cuisle icon into the PNGs and favicon the README, dashboard and
# app need. src/cuisle/icons/icon.svg is the single source of the artwork:
# change it, run this, and commit the SVG and every generated file in one
# commit.
#
# Requires ImageMagick (`magick`). The SVG is deliberately flat: ImageMagick's
# built-in MSVG renderer drops gradients, transforms, dashes, filters and even
# stroked paths, and can silently draw a transformed group in the wrong place.
# Keep the art to filled rectangles, circles and polygons only.
#
# Assisted-by: Claude Code (DeepSeek Flash, effort: high)

set -euo pipefail

cd "$(dirname "$0")/.."

SVG="src/cuisle/icons/icon.svg"
DIR="src/cuisle/icons"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# Render once at high density, then resize. -strip removes the date:create and
# date:modify metadata ImageMagick embeds, so re-running never churns git with
# identical-looking PNGs.
magick -background none -density 288 "$SVG" -strip -resize 1024x1024 "$TMP/base.png"

for size in 16 32 48 64 128 192 256 512 1024; do
  magick "$TMP/base.png" -strip -resize "${size}x${size}" -depth 8 \
    "PNG32:$DIR/icon-$size.png"
done

# iOS applies its own mask and renders a transparent touch icon as black, so the
# 180px icon is full-bleed: the icon's own background colour fills the canvas,
# which makes the rounded corners disappear into it.
magick -size 180x180 "xc:#0B2230" \
  \( "$TMP/base.png" -resize 180x180 \) -gravity center -composite \
  -strip -depth 8 "PNG32:$DIR/apple-touch-icon.png"

# Multi-size favicon: 16, 32 and 48 pixels.
magick "$DIR/icon-16.png" "$DIR/icon-32.png" "$DIR/icon-48.png" \
  -strip "$DIR/favicon.ico"

# Verify transparency survived on the rounded icon: the corner must be
# transparent and the minimum alpha must be 0.
magick "$DIR/icon-192.png" \
  -format 'icon-192 corner %[pixel:p{2,2}] min-alpha %[fx:minima.a]\n' info:

echo "wrote:"
ls -1 "$DIR"

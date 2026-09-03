# Take the Board brand assets

This package is the canonical, local identity for Take the Board. It is an
independent rivalry-scoreboard system and intentionally contains no school
names, mascots, seals, university colors, or athletics typography. The current
artwork is the approved Claim Marker concept supplied for this product.

## Canonical files

- `ttb-lockup.svg` is the primary light-background full lockup, using the
  supplied Claim Marker board, white T, red takeover tab, and wordmark. Its
  trimmed viewBox removes unused canvas while preserving the artwork.
- `ttb-lockup-reversed.svg` is the dark-background lockup used where white
  wordmark text is required, such as the branded error pages.
- `ttb-mark.svg` is the square board panel cropped from the lockup for
  browser/app icon use. It keeps the same charcoal board, white T, and red
  takeover tab so the favicon and full logo are one system.
- `favicon.ico`, `ttb-mark-32.png`, and `apple-touch-icon.png` are raster
  exports of the small mark. The ICO contains 16px, 32px, and 48px images.

## Palette

| Token | Value | Use |
| --- | --- | --- |
| Charcoal | `#171A1E` | Structure, wordmark, dark surfaces |
| Signal red | `#D63A46` | Claim marker and selective emphasis |
| Paper | `#FBFAF7` | Light lockup field and reversed mark detail |

Keep the red selective. The board panel is a neutral game surface; the red tab
is the claim signal, not a university or league reference. Do not recolor the
mark to match a school. Use the full lockup when the product name needs to be
visible; use the square panel only when space is limited.

There is intentionally no web manifest: the current site is not claiming to
be an installable PWA. If that product decision changes, add a manifest and
192/512px purpose-specific exports from `ttb-mark.svg` rather than treating
the favicon as the app icon by default.

## Replacement guidance

The SVGs in this directory are the canonical source. Template references use
stable logical static paths with Django/WhiteNoise cache-busting, so a later
professional designer can replace these files in place without rewriting
templates. Preserve the `ttb-mark.svg` square viewBox and the lockup filenames,
or update only the documented static references and this note.

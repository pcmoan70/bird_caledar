# Field notes — house style

You are compiling **field notes** for a bird calendar: what an experienced
observer would write in a notebook to identify the species and to rule out the
species it can be confused with.

## Sources — the hard rule

Every statement must come from the **sources given in the batch file** (the
species' own `sources` texts in English, German and Swedish, its
`measures_cm_g`, and the `text` of each confusion candidate). German and
Swedish sources may be used — translate them.

- Do **not** add anything from your own knowledge, however certain you are.
- If a fact is not in the sources, leave it out. Short notes are fine.
- Never invent a measurement. Use only `measures_cm_g` (already cross-checked
  between editions) or figures stated in the source text.
- Do not copy long runs of source wording — compress into note register.

## Register

Terse, telegraphic, present tense — a notebook, not an encyclopaedia.

- No sentence subjects like "The great tit is…": write "Large tit; …".
- Semicolons between marks; no bullet characters; no citations; no headings.
- British spelling: grey, colour, moustachial.
- Standard topography: crown, nape, mantle, scapulars, coverts, primaries,
  rump, vent, undertail-coverts, supercilium, malar, lores, iris, tarsus.
- Sexes: give the male first, then "Female:", then "Juvenile:" — only when the
  sources describe a real difference.

## Fields (JSON keys)

| key | content | limit |
|---|---|---|
| `jizz` | size, build, proportions, tail/bill/wing shape; open with the length from `measures_cm_g` (e.g. "12.5–15 cm."), add wingspan/mass only if given | ≤ 40 words |
| `plumage` | the marks that identify it, head to tail; sex/age differences when sourced | ≤ 60 words |
| `bare_parts` | bill, legs, iris colour — omit the key entirely if unsourced | ≤ 25 words |
| `field` | flight action, gait, posture, habitat, feeding or other behaviour usable for ID; voice only if the sources describe it | ≤ 40 words |
| `similar` | one entry per confusion candidate (see below) | — |
| `unsupported` | list of things you would normally note but the sources do not support (may be empty) | — |

## `similar` entries

One object per species in `confusion_candidates`, **in the order given**:

```json
{"code": "blutit", "name": "Eurasian Blue Tit", "separation": "..."}
```

`separation` (≤ 30 words) must state what actually separates the two **in the
field**, grounded in either species' provided text or their measurements —
plumage marks first, structure and size second. Write it as an instruction to
the observer, e.g. "Smaller and blue-capped; lacks the black central belly
stripe and white cheeks are ringed blue."

- If the sources give you nothing to separate them beyond size, say exactly
  that, using the measurements ("Little else in the sources: separated here on
  size, 19–21 cm against 28–34 cm.").
- If `confusion_candidates` is empty, use `"similar": []` and, when the sources
  support it, note distinctiveness in `field` (e.g. "Unmistakable in range.").
- Never add a confusion species that is not in the candidate list.

## Output

Write **one JSON file** with an array of objects, one per species in the batch,
in the same order, each shaped exactly:

```json
{
  "code": "gretit1",
  "jizz": "12.5–15 cm, 14–22 g. Large, robust tit; …",
  "plumage": "…",
  "bare_parts": "…",
  "field": "…",
  "similar": [{"code": "…", "name": "…", "separation": "…"}],
  "unsupported": []
}
```

Valid JSON, UTF-8, no trailing commentary. Keep `code` exactly as given.

# Armaly 1983 reference data

Source: Armaly, B. F., Durst, F., Pereira, J. C. F., & Schönung, B. (1983). Experimental and theoretical investigation of backward-facing step flow. *Journal of Fluid Mechanics*, 127, 473–496.

## What's here

| File | Quantity | Source figure |
|------|----------|---------------|
| `reattachment_length.json` | x_r / h as a function of Re | Figure 4 |

Only the reattachment-length data ships with the case. Armaly's velocity-profile data (Fig. 5) is all in the **laminar** regime (Re ≲ 1300), whereas the baseline pitzDaily case runs in the fully-turbulent plateau (Re ≈ 50,800 by Armaly's convention) — so there is no apples-to-apples turbulent velocity profile to compare against in this paper. For turbulent profiles, **Driver–Seegmiller (1985), AIAA Journal 23(2):163–171** at Re_h = 37,500 is the closer reference, though it uses a much lower expansion ratio (~1.13 vs pitzDaily's ~2.0).

`reattachment_length.json` alone is enough to validate the headline metric (the x_r/h ≈ 6 turbulent plateau).

## Provenance

`reattachment_length.json` is hand-encoded from approximate visual readings of Armaly's Fig. 4 (the reattachment-length-vs-Re plot; the paper reports it graphically, not in a table), cross-checked against secondary citations (Erturk 2008 *Comput. Fluids*; Le–Moin–Kim 1997 *JFM* 330; Barbi & Erturk 2008 *Comput. Fluids* 37). Engineering precision is roughly ±1 step height. Each data point carries a `source` tag inside the JSON. Note: the laminar peak is commonly cited as x_r/h ≈ 15–16 near Re ≈ 1200; the value tabulated here (14.0) is at the low edge of that spread. Armaly's measured range is 70 < Re < 8000 (laminar Re < 1200, transitional 1200 < Re < 6600, turbulent Re > 6600).

## JSON schema

Loose by design — dicts of named arrays. Example for a velocity profile dataset:

```json
{
  "reynolds_number": 800,
  "x_over_h": 4,
  "y_over_h": [0.0, 0.1, 0.2, ...],
  "u_over_U0": [0.0, -0.12, -0.08, ...],
  "notes": "Digitized from Figure 5a using WebPlotDigitizer v5.x"
}
```

For `reattachment_length.json`, an array of `{reynolds_number, x_r_over_h}` entries.

## Adding a new reference dataset

1. Get the figure from the journal PDF (JFM is usually institutionally accessible; if not, secondary compilations like the ERCOFTAC Classic Collection are an option).
2. Use WebPlotDigitizer (https://automeris.io) to extract points.
3. Export as CSV.
4. Convert to JSON matching the schema above.
5. Commit the JSON (not the CSV or the PDF).

## Known issues in the original data

- Armaly's experiment has a finite spanwise aspect ratio (~36:1). For Re > ~400 there are measurable 3D effects that a 2D simulation can't capture. Document this limitation when narrating the case.
- Digitizing a printed figure introduces ~1% noise. Don't tighten validation tolerances below that floor.

## Alternative references

- **Driver–Seegmiller (1985), AIAA Journal 23(2):163–171** — turbulent BFS at Re_h = 37,500, much closer to the pitzDaily Re. Lower expansion ratio (~1.13).
- **Kasagi & Matsunaga (1995)** — DNS, clean numerical reference but different geometry.
- **ERCOFTAC Classic Collection Case 31** — compiled Armaly data, easier to access than the original JFM paper.

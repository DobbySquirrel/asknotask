# System architecture figure (IEEE ICDE)

Vector system-overview figure for the paper: staged detection → type detectors
(data observability) → uncertainty gate (model resolvability) → parsing, with an
offline strip for JEV training and threshold selection.

- Canvas: 7.16 in × 2.754 in (aspect ratio 2.6:1, IEEE two-column `figure*` width)
- Palette (Okabe–Ito subset): `#0072B2`, `#56B4E9`, `#E69F00`, `#009E73`,
  `#BBBBBB`, `#F2F2F2` (stage backgrounds), `#333333` (text and arrows)
- 0.75 pt strokes, flat fills, sans-serif text (Helvetica/Arial metrics)

## Outputs

| File | Use |
| --- | --- |
| `figure/architecture.pdf` | Include in LaTeX (fonts embedded) |
| `figure/architecture.svg` | Editable vector source (Inkscape / Illustrator) |
| `figure/architecture.png` | 600 dpi raster preview |

```latex
\begin{figure*}[t]
  \centering
  \includegraphics[width=\textwidth]{figure/architecture.pdf}
  \caption{System overview.}
  \label{fig:overview}
\end{figure*}
```

## Regenerate

The figure is produced by a single script; every coordinate is in points, and
text is placed with metrics from Liberation Sans (metric-compatible with Arial),
so layout is identical across renderers. The script prints a warning when any
label would overflow its box.

```bash
pip install -r requirements.txt
python3 make_figure.py
```

Needs the Liberation Sans and DejaVu Sans fonts (`fonts-liberation`,
`fonts-dejavu-core` on Debian/Ubuntu). DejaVu Sans supplies ⟨ ⟩ ⊕, which
Liberation Sans lacks.

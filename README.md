# System figures (IEEE ICDE)

Vector figures for the paper, generated from Python scripts. Every coordinate is
in points, and text is positioned from Liberation font metrics
(metric-compatible with Helvetica / Times / Courier), so the layout is identical
in every renderer. Each script prints a warning when a label would overflow its
box or fall below the 6 pt minimum.

| Figure | Size | Script | Outputs |
| --- | --- | --- | --- |
| System overview with running example | 7.16 in × 3.4 in | `make_overview.py` | `figure/overview.{pdf,svg,png}` |
| Motivating example (single column) | 3.5 in × 3.58 in | `make_motivation.py` | `figure/motivation.{pdf,svg,png}` |
| Architecture with offline strip | 7.16 in × 2.754 in (2.6:1) | `make_figure.py` | `figure/architecture.{pdf,svg,png}` |

The PDFs embed their fonts and go straight into LaTeX; the SVGs are editable in
Inkscape / Illustrator; the PNGs are 600 dpi previews.

```latex
\begin{figure*}[t]
  \centering
  \includegraphics[width=\textwidth]{figure/overview.pdf}
  \caption{System overview on a running example.}
  \label{fig:overview}
\end{figure*}
```

## Overview figure conventions

- Card colours: `#56B4E9` settled by data, `#0072B2` auto-resolved, `#E69F00`
  asked, `#BBBBBB` removed / dropped, `#009E73` correct SQL; `#F4F4F4` panel
  backgrounds; `#333333` text and arrows.
- Labels in sans-serif, code in monospace, math in italic serif; minimum 6 pt.
- 0.7 pt strokes, 3 pt corner radius, no gradients or shadows.
- The three example cards (tags 1–3) keep their colour from the question
  highlight through to the clarification sentence in E′.

`figlib.py` holds the shared drawing kit (markup: `$math$`, `` `mono` ``,
`!{bold}`, `/{italic}`, `_{sub}`, `^{sup}`).

## Regenerate

```bash
pip install -r requirements.txt
python3 make_overview.py
python3 make_motivation.py
python3 make_figure.py
```

Needs the Liberation and DejaVu fonts (`fonts-liberation`, `fonts-dejavu-core`
on Debian/Ubuntu). DejaVu supplies symbols Liberation lacks (⟨ ⟩ ⊕ ∉ ∪ ⊥ ∈).

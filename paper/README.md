# Paper figures (IEEE ICDE)

This directory is the paper subtree. All figure scripts and outputs live in `figure/`. Every coordinate is in
points, and text is positioned from Liberation font metrics
(metric-compatible with Helvetica / Times / Courier), so the layout is
identical in every renderer. Each script prints a warning when a label
would overflow its box or fall below the 6 pt minimum.

| Figure | Size | Script | Outputs |
| --- | --- | --- | --- |
| System overview with running example | 7.16 in × 3.4 in | `figure/make_overview.py` | `figure/overview.{pdf,svg,png}` |
| Motivating example (single column) | 3.5 in × 4.53 in | `figure/make_motivation.py` | `figure/motivation.{pdf,svg,png}` |
| Offline training + online JEV vs. training-free scorer | 7.16 in × 3.5 in | `figure/make_pipeline_compare.py` | `figure/pipeline_compare.{pdf,svg,png}` |
| Fig. 4, accuracy versus questions (matplotlib) | 7.16 in × 2.1 in | `figure/make_pareto.py` | `figure/pareto.pdf` |
| Fig. 5, user-study confusion matrices (matplotlib) | 3.5 in × 1.85 in | `figure/make_user_pairs.py` | `figure/user_pairs.pdf` |

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

- Card colours: `#6CB6E3` settled by data, `#2F7FB8` auto-resolved, `#E8922A`
  asked, `#C9CED4` removed / dropped, `#3BAF9F` correct SQL; `#F3F6F9` panel
  backgrounds; `#55606C` text and arrows. The motivating example keeps a
  slightly darker ink, `#2A3138`.
- Labels in sans-serif, code in monospace, math in italic serif; minimum 6 pt.
- 0.7 pt strokes, 5 pt corner radius (5.5 pt on the motivating example), no gradients or shadows.
- The three example cards (tags 1–3) keep their colour from the question
  highlight through to the clarification sentence in E′.

`figure/figlib.py` holds the shared drawing kit (markup: `$math$`, `` `mono` ``,
`!{bold}`, `/{italic}`, `_{sub}`, `^{sup}`).

## Regenerate

```bash
pip install -r requirements.txt
cd figure
python3 make_overview.py
python3 make_motivation.py
python3 make_pipeline_compare.py
python3 make_pareto.py
python3 make_user_pairs.py
```

`make_pareto.py` and `make_user_pairs.py` plot the numbers frozen for the
paper by default. With `--from-outputs`, `make_pareto.py` reads
`outputs/<ds>/eval/qwen_coder/`. `make_user_pairs.py` reads
`outputs/user_study/replay` (or another directory passed as `--replay`).
They need `matplotlib` and `numpy`.

Needs the Liberation and DejaVu fonts (`fonts-liberation`, `fonts-dejavu-core`
on Debian/Ubuntu). DejaVu supplies symbols Liberation lacks (⟨ ⟩ ⊕ ∉ ∪ ⊥ ∈).

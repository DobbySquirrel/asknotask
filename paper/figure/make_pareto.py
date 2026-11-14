"""Fig. 4: accuracy versus questions (Qwen3-Coder, EX against y*).

By default the plot uses the numbers frozen for the paper (step1/theta_curve
and Table II). With --from-outputs it reads the evaluation files
outputs/<ds>/eval/qwen_coder/{never_ask,clear,ambisql,ours_wo_scorer,
ours_theta<θ>}.json instead.
"""
import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent

N = {"BIRD": 498, "AMBROSIA": 1149, "CLAMBSQL": 1400}
DS = {"BIRD": "bird_arcwise", "AMBROSIA": "ambrosia", "CLAMBSQL": "clambsql"}
THETA = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
SELECTED = THETA.index(0.5)

# (hits, Q) per theta, retrained scorer on the frozen A+B+C ambiguities
PAPER_CURVE = {
    "BIRD": ([333, 333, 330, 331, 333, 328, 326, 325, 326],
             [2.93, 2.88, 2.75, 2.40, 1.89, 1.56, 1.15, 0.90, 0.64]),
    "AMBROSIA": ([538, 539, 541, 541, 547, 545, 529, 509, 503],
                 [2.55, 2.54, 2.49, 2.21, 1.82, 1.58, 1.11, 0.80, 0.52]),
    "CLAMBSQL": ([803, 804, 802, 795, 797, 788, 783, 775, 762],
                 [2.89, 2.87, 2.72, 2.38, 1.97, 1.63, 1.13, 0.84, 0.55]),
}
# (hits, Q) from Table II
PAPER_BASE = {
    "BIRD": {"Never-Ask": (295, 0), "CLEAR": (299, 0.29), "AmbiSQL": (299, 1.91),
             "Ours w/o scorer": (333, 2.93)},
    "AMBROSIA": {"Never-Ask": (140, 0), "CLEAR": (195, 0.75), "AmbiSQL": (232, 2.00),
                 "Ours w/o scorer": (538, 2.55)},
    "CLAMBSQL": {"Never-Ask": (643, 0), "CLEAR": (689, 1.18), "AmbiSQL": (686, 1.88),
                 "Ours w/o scorer": (803, 2.89)},
}
METHOD_FILE = {"Never-Ask": "never_ask", "CLEAR": "clear", "AmbiSQL": "ambisql",
               "Ours w/o scorer": "ours_wo_scorer"}

GRAY, BLUE = "#7a7a7a", "#1f5fa8"
MARK = {"Never-Ask": ("s", GRAY, "white"), "CLEAR": ("^", GRAY, GRAY),
        "AmbiSQL": ("o", GRAY, GRAY), "Ours w/o scorer": ("D", BLUE, "white")}


def paper_data():
    curve = {b: ([100.0 * h / N[b] for h in hs], qs) for b, (hs, qs) in PAPER_CURVE.items()}
    base = {b: {m: (100.0 * h / N[b], q) for m, (h, q) in rows.items()}
            for b, rows in PAPER_BASE.items()}
    return curve, base


def outputs_data(outputs):
    sys.path.insert(0, str(REPO / "scripts"))
    import json
    from check_manifest import load_exq, load_jsonl, measure

    spec = json.loads((outputs / "analysis" / "expected.json").read_text())
    golds = spec.get("gold", {})

    def ex_q(ds, name):
        path = outputs / ds / "eval" / "qwen_coder" / f"{name}.json"
        if not path.exists():
            path = path.with_suffix(".jsonl")
        gold = golds.get(ds, "gold")
        raw = load_jsonl(path, gold) if path.suffix == ".jsonl" else load_exq(path, None, gold)
        got = measure(raw, spec["sizes"][ds])
        return got["ex"], got["q"]

    curve, base = {}, {}
    for b, ds in DS.items():
        pts = [ex_q(ds, f"ours_theta{t}") for t in THETA]
        curve[b] = ([p[0] for p in pts], [p[1] for p in pts])
        base[b] = {m: ex_q(ds, f) for m, f in METHOD_FILE.items()}
    return curve, base


def plot(curve, base, out):
    plt.rcParams.update({"font.size": 8, "font.family": "serif", "axes.linewidth": 0.6})
    fig, axes = plt.subplots(1, 3, figsize=(7.16, 2.1))
    for ax, b in zip(axes, N):
        for name, (ex, q) in base[b].items():
            m, ec, fc = MARK[name]
            ax.scatter(q, ex, marker=m, facecolor=fc, edgecolor=ec, linewidth=0.9,
                       s=26, zorder=3, label=name)
        ex, q = curve[b]
        ax.plot(q, ex, "-", marker="o", color=BLUE, ms=2.2, lw=1.0,
                label="Ours (scorer, varying $\\theta$)", zorder=2)
        ax.scatter(q[SELECTED], ex[SELECTED], marker="*", s=140, color=BLUE,
                   edgecolor="#0b2f5c", linewidth=0.6, zorder=4, label=r"Ours at $\theta^*$")
        ax.set_title("BIRD-Arcwise" if b == "BIRD" else b, fontsize=9)
        ax.set_xlabel("Questions per instance ($Q$)")
        ax.set_xlim(-0.1, 3.1)
        ax.grid(alpha=0.3, lw=0.4)
    axes[0].set_ylabel("EX (%)")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=7, frameon=False,
               fontsize=7, bbox_to_anchor=(0.5, 1.04), handletextpad=0.3, columnspacing=1.0)
    fig.tight_layout(rect=(0, 0, 1, 0.9))
    fig.savefig(out, bbox_inches="tight")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--from-outputs", action="store_true", help="read outputs/ instead of the paper numbers")
    ap.add_argument("--outputs", type=Path, default=REPO / "outputs")
    ap.add_argument("--out", type=Path, default=HERE / "pareto.pdf")
    args = ap.parse_args()
    curve, base = outputs_data(args.outputs) if args.from_outputs else paper_data()
    plot(curve, base, args.out)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()

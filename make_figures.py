"""Regenerate allocation_clause_count.pdf and allocation_solve_time.pdf
from the experiment CSV.

Usage:  python make_figures.py path/to/results.csv
Needs:  pandas, matplotlib
Optional (Persian labels inside the figures):
        pip install arabic-reshaper python-bidi
"""
import sys
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

matplotlib.rcParams["pdf.fonttype"] = 42   # embed real fonts, not Type 3

csv_path = sys.argv[1] if len(sys.argv) > 1 else "results.csv"
df = pd.read_csv(csv_path)
df = df[df["family"] == "allocation"]

ORDER = ["pairwise", "seqcounter", "cardnetwrk"]
STYLE = {"pairwise": ("o", "-"), "seqcounter": ("s", "--"), "cardnetwrk": ("^", ":")}

try:
    import arabic_reshaper
    from bidi.algorithm import get_display
    fa = lambda s: get_display(arabic_reshaper.reshape(s))
    matplotlib.rcParams["font.family"] = "Tahoma"   
    NAMES = {"pairwise": fa("دوبه‌دو"),
             "seqcounter": fa("شمارندهٔ متوالی"),
             "cardnetwrk": fa("شبکهٔ کاردینالیتی")}
    XL = fa("اندازهٔ مسئله (n)")
    YL1 = fa("تعداد کل بندها")
    YL2 = fa("میانگین زمان حل (ثانیه)")
except ImportError:
    NAMES = {"pairwise": "Pairwise",
             "seqcounter": "Sequential counter",
             "cardnetwrk": "Cardinality network"}
    XL, YL1, YL2 = "Problem size (n)", "Total clauses", "Mean solve time (s)"


def draw(table, ylabel, out):
    fig, ax = plt.subplots(figsize=(6.4, 4.0))
    for enc in ORDER:
        s = table[enc]
        m, ls = STYLE[enc]
        ax.plot(s.index, s.values, marker=m, linestyle=ls, label=NAMES[enc])
    ax.set_yscale("log")
    ax.set_xticks(sorted(table.index))
    ax.set_xlabel(XL)
    ax.set_ylabel(ylabel)
    ax.grid(True, which="both", alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)


# Figure 1: total clauses (depends only on n and encoding)
clauses = df.groupby(["size", "encoding"])["n_clauses"].mean().unstack("encoding")
draw(clauses, YL1, "allocation_clause_count.pdf")

# Figure 2: mean solve time over SOLVED instances only
solved = df[df["status"] == "solved"]
solve = solved.groupby(["size", "encoding"])["solve_time"].mean().unstack("encoding")
draw(solve, YL2, "allocation_solve_time.pdf")

print("wrote allocation_clause_count.pdf and allocation_solve_time.pdf")
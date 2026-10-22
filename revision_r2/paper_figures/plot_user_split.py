"""Block diagram of the CERT r5.2 user-disjoint split (Fig. user_split).

Drawn at the IEEE Access column width (85.29 mm) so that all text is >= 9 pt
when the PDF is included at \\columnwidth.
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

matplotlib.rcParams.update({
    "font.family": "serif",
    "font.serif": ["Liberation Serif", "Times New Roman", "DejaVu Serif"],
    "pdf.fonttype": 42,
    "font.size": 9,
})

W, H = 85.29 / 25.4, 2.97
fig = plt.figure(figsize=(W, H))
ax = fig.add_axes([0, 0, 1, 1])
ax.set_xlim(0, 100)
ax.set_ylim(1, 90)
ax.axis("off")

EDGE = "#2b2b2b"
DEV = "#dbe8f5"
HOLD = "#fbe3cf"
TOP = "#eeeeee"
SEAL = "#ffffff"


def box(x, y, w, h, text, fc, ls="-", bold=False, ec=EDGE, color="black"):
    p = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=1.6",
                       fc=fc, ec=ec, lw=0.8, ls=ls)
    ax.add_patch(p)
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=9,
            fontweight="bold" if bold else "normal", color=color,
            linespacing=1.15)


def arrow(x0, y0, x1, y1):
    ax.annotate("", xy=(x1, y1), xytext=(x0, y0),
                arrowprops=dict(arrowstyle="-|>", lw=0.8, color=EDGE,
                                shrinkA=0, shrinkB=0, mutation_scale=7))


def line(xs, ys):
    ax.plot(xs, ys, color=EDGE, lw=0.8, solid_capstyle="butt")


# Row 1: release and sealed test partition
box(2, 78, 60, 10, "CERT r5.2: 2,000 users", TOP, bold=True)
box(66, 78, 32, 10, "TEST partition:\nsealed, not used", SEAL, ls="--",
    ec="#777777", color="#444444")

# Split connector
line([32, 32], [78, 72])
line([28, 78], [72, 72])
arrow(28, 72, 28, 62)
arrow(78, 72, 78, 62)
ax.text(53, 66.5, "stratified user split", ha="center", va="center",
        fontsize=9, style="italic")

# Row 2: user groups
box(2, 50, 52, 12, "1,500 development users\n(74 insiders)", DEV, bold=True)
box(58, 50, 40, 12, "500 held-out users\n(25 insiders)", HOLD, bold=True)

# Row 3: periods and roles
arrow(14, 50, 14, 44)
arrow(41, 50, 41, 44)
arrow(78, 50, 78, 44)
box(2, 22, 24, 22, "TRAIN\nperiod:\nmodel\nfitting", DEV)
box(28, 22, 26, 22, "VALID.\nperiod:\ncheckpoints,\nthresholds", DEV)
box(58, 22, 40, 22, "TRAIN and VALID.\nperiods: scored\nonce, after all\nmodels fixed", HOLD)

# Window counts
for x, n, p in [(14, "591,000", "3,040"), (41, "48,000", "473"),
                (78, "213,000", "1,172")]:
    ax.text(x, 11, f"{n}\nwindows\n({p} pos.)", ha="center", va="center",
            fontsize=9, linespacing=1.15)

fig.savefig("/home/claude/work/ms_r3/figures/R3_user_split.pdf")
fig.savefig("/home/claude/work/ms_r3/figures/R3_user_split_preview.png", dpi=200)

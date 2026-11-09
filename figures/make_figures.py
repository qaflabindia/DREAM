"""Render results figures from artifacts. Static PNGs for the manuscript."""
import json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SURF, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
C = {"blue": "#2a78d6", "orange": "#eb6834", "aqua": "#1baf7a", "yellow": "#eda100"}
plt.rcParams.update({"font.size": 9, "axes.edgecolor": INK2, "axes.labelcolor": INK, "xtick.color": INK2,
                     "ytick.color": INK2, "axes.facecolor": SURF, "figure.facecolor": SURF,
                     "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
                     "grid.color": GRID, "grid.linewidth": 0.6})

def err(v):
    return [[v["mean"] - v["ci95"][0]], [v["ci95"][1] - v["mean"]]]

# Figure 2: E1 signal sweep
e1 = json.load(open("artifacts/e1_learned_salience.json"))["signal_sweep_ntrain50"]
xs = [float(s) for s in e1]
fig, ax = plt.subplots(figsize=(5.6, 3.4))
arms = [("bayes", "True propensity (bound)", C["blue"], "s"), ("learned", "Learned salience", C["orange"], "o"),
        ("recency", "Recency (last 16)", C["aqua"], "^"), ("random", "Random importance", C["yellow"], "D")]
for key, label, col, mk in arms:
    ys = [e1[s][key]["mean"] for s in e1]
    lo = [e1[s][key]["mean"] - e1[s][key]["ci95"][0] for s in e1]
    hi = [e1[s][key]["ci95"][1] - e1[s][key]["mean"] for s in e1]
    ax.errorbar(xs, ys, yerr=[lo, hi], color=col, marker=mk, ms=6, lw=2, capsize=3, label=label)
    dy = {"bayes": 7, "learned": -7}.get(key, 0)
    ax.annotate(label, (xs[-1], ys[-1]), xytext=(8, dy), textcoords="offset points", va="center", color=INK, fontsize=8)
ax.set_xlabel("Strength of feature–need relationship, s (0 = no information)")
ax.set_ylabel("Share of future-needed items retained")
ax.set_ylim(0, 1); ax.set_xlim(-0.1, 2.9); ax.set_xticks(xs)
ax.legend(loc="upper left", frameon=False, fontsize=8)
fig.tight_layout(); fig.savefig("figures/e1_salience.png", dpi=200); plt.close(fig)

# Figure 3: E2 small multiples
e2 = json.load(open("artifacts/e2_counterfactual_transfer.json"))["exact_authority"]
fig, axes = plt.subplots(1, 3, figsize=(7.6, 3.0), sharey=True)
eps = [0.0, 0.1, 0.3]
arms = [("dream", "DREAM (tested promotion)", C["blue"], "s"), ("retrieval+", "Retrieval, budget-matched", C["orange"], "o"),
        ("reflection+", "Reflection, budget-matched", C["aqua"], "^")]
for ax, n in zip(axes, (1, 3, 10)):
    for key, label, col, mk in arms:
        vals = [e2[f"ntrain={n},eps={e}"][key] for e in eps]
        ax.errorbar(eps, [v["mean"] for v in vals],
                    yerr=[[v["mean"] - v["ci95"][0] for v in vals], [v["ci95"][1] - v["mean"] for v in vals]],
                    color=col, marker=mk, ms=6, lw=2, capsize=3, label=label)
    base = [e2[f"ntrain={n},eps={e}"]["base"]["mean"] for e in eps]
    ax.plot(eps, base, color=INK2, lw=1, ls="--")
    ax.annotate("no learning", (0.3, base[-1]), xytext=(0, -10), textcoords="offset points", ha="right", color=INK2, fontsize=7)
    ax.set_title(f"{n} training episode{'s' if n > 1 else ''} per family", fontsize=9, color=INK)
    ax.set_xticks(eps); ax.set_xlabel("Feedback error rate")
axes[0].set_ylabel("Accuracy on unseen tasks"); axes[0].set_ylim(0.5, 1.0)
handles, labels = axes[0].get_legend_handles_labels()
fig.legend(handles, labels, loc="lower center", ncol=3, frameon=False, fontsize=8)
fig.tight_layout(rect=(0, 0.08, 1, 1)); fig.savefig("figures/e2_transfer.png", dpi=200); plt.close(fig)
print("ok")

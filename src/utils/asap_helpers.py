#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
utils/asap_helpers.py

Iterative ASAP‐minimization wrapper helpers for VROOM.

Adds detailed logging to each step: initial solve, dichotomy, backward search,
filtering, and plotting.
"""

import copy
import logging
import os
import sys
import matplotlib.pyplot as plt
from utils.vroom import solve

# ── Logging setup ────────────────────────────────────────────────
LOG_LEVEL = os.getenv("ASAP_LOG_LEVEL", "DEBUG").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.DEBUG),
    format="%(asctime)s | %(levelname)s | %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("asap_helpers")


def filter_dominated(solutions):
    """Remove any solution strictly dominated on both completion time and cost."""
    completion_times = [
        max(r["steps"][-1]["arrival"] for r in sol["routes"]) for sol in solutions
    ]
    costs = [sol["summary"]["cost"] for sol in solutions]
    to_remove = []
    for i in range(len(solutions)):
        for j in range(len(solutions)):
            if i == j:
                continue
            if completion_times[j] < completion_times[i] and costs[j] < costs[i]:
                to_remove.append(i)
                break
    for idx in sorted(set(to_remove), reverse=True):
        log.debug(
            "filter_dominated: Removing solution %s (completion=%s cost=%s)",
            idx,
            completion_times[idx],
            costs[idx],
        )
        solutions.pop(idx)


def filter_unique(solutions):
    """Remove duplicate solutions with identical completion time and cost."""
    completion_times = [
        max(r["steps"][-1]["arrival"] for r in sol["routes"]) for sol in solutions
    ]
    costs = [sol["summary"]["cost"] for sol in solutions]
    to_remove = []
    for i in range(len(solutions)):
        for j in range(i + 1, len(solutions)):
            if j in to_remove:
                continue
            if completion_times[i] == completion_times[j] and costs[i] == costs[j]:
                log.debug("filter_unique: Removing duplicate solution %s", j)
                to_remove.append(j)
                break
    for idx in sorted(set(to_remove), reverse=True):
        solutions.pop(idx)


def dichotomy(data, cl_args, first_solution):
    """Dichotomic search reducing the global end‐time to minimize completion."""
    log.debug("dichotomy: starting")
    init_input = copy.deepcopy(data)
    solutions = []

    # record the initial solution
    sol0 = copy.deepcopy(first_solution)
    sol0["origin"] = "initial"
    solutions.append(sol0)
    init_ct = max(r["steps"][-1]["arrival"] for r in sol0["routes"])
    log.debug(
        "dichotomy: initial completion=%s cost=%s", init_ct, sol0["summary"]["cost"]
    )

    # get bounds
    end_dates = [r["steps"][-1]["arrival"] for r in first_solution["routes"]]
    earliest, latest = min(end_dates), max(end_dates)

    # adjust for any vehicle without a time window
    earliest_TW = min(
        (v.get("time_window", [0, latest])[0] for v in init_input["vehicles"]),
        default=0,
    )
    if len(first_solution["routes"]) < len(init_input["vehicles"]):
        earliest = earliest_TW

    # dichotomy loop
    while True:
        candidate = (earliest + latest) // 2
        if candidate in (earliest, latest):
            break

        log.debug(
            "dichotomy: trying end_time=%s (bounds %s–%s)", candidate, earliest, latest
        )
        current = copy.deepcopy(init_input)
        # shrink/discard vehicles
        for idx in reversed(range(len(current["vehicles"]))):
            tw0, tw1 = current["vehicles"][idx].get("time_window", [0, latest])
            if candidate < tw0:
                current["vehicles"].pop(idx)
            else:
                current["vehicles"][idx]["time_window"][1] = candidate

        log.debug("dichotomy: invoking core solver")
        current_sol = solve(current, cl_args)
        ct = (
            max(r["steps"][-1]["arrival"] for r in current_sol["routes"])
            if current_sol["routes"]
            else None
        )
        unassigned = current_sol["summary"].get("unassigned")
        cost = current_sol["summary"].get("cost")
        log.debug(
            "dichotomy: result code=%s unassigned=%s completion=%s cost=%s",
            current_sol.get("code"),
            unassigned,
            ct,
            cost,
        )

        if unassigned == 0:
            current_sol["origin"] = "dichotomy"
            solutions.append(current_sol)
            latest = candidate
        else:
            earliest = candidate

    return solutions


def backward_search(data, cl_args, first_solution):
    """Naïve backward time-window reduction search for extra Pareto points."""
    log.debug("backward_search: starting")
    current = copy.deepcopy(data)
    solutions = []
    latest = max(r["steps"][-1]["arrival"] for r in first_solution["routes"])
    unassigned = first_solution["summary"].get("unassigned", 0)

    while unassigned == 0:
        log.debug("backward_search: latest=%s", latest)
        sol = solve(current, cl_args)
        ct = max(r["steps"][-1]["arrival"] for r in sol["routes"])
        cost = sol["summary"].get("cost")
        unassigned = sol["summary"].get("unassigned")
        log.debug(
            "backward_search: code=%s unassigned=%s completion=%s cost=%s",
            sol.get("code"),
            unassigned,
            ct,
            cost,
        )

        sol["origin"] = "backward_search"
        solutions.append(sol)

        latest -= 1
        for idx in reversed(range(len(current["vehicles"]))):
            tw0 = current["vehicles"][idx]["time_window"][0]
            if latest < tw0:
                current["vehicles"].pop(idx)
            else:
                current["vehicles"][idx]["time_window"][1] = latest

    return solutions


def plot_pareto_front(indicators, pareto_plot_file, full_Y_scale=False):
    """Scatter plot of completion vs cost for Pareto front."""
    log.info("plot_pareto_front: saving plot to %s", pareto_plot_file)
    fig, ax = plt.subplots()
    ax.set_xlabel("Completion time")
    ax.set_ylabel("Cost")

    styles = {
        "initial": {"marker": "s", "edgecolor": "green", "linewidth": 1},
        "dichotomy": {"marker": "^", "edgecolor": "red", "linewidth": 0.7},
        "backward_search": {"marker": "o", "edgecolor": "blue", "linewidth": 0.5},
    }

    max_cost = max(i["cost"] for i in indicators)
    for origin in styles:
        pts = [
            (i["completion"], i["cost"]) for i in indicators if i["origin"] == origin
        ]
        if not pts:
            continue
        xs, ys = zip(*pts)
        style = styles[origin]
        ax.scatter(
            xs,
            ys,
            facecolor="none",
            edgecolor=style["edgecolor"],
            marker=style["marker"],
            linewidth=style["linewidth"],
        )

    if full_Y_scale:
        ax.set_ylim(0, max_cost * 1.05)

    plt.savefig(pareto_plot_file, bbox_inches="tight")
    plt.close(fig)


def solve_asap(problem):
    """
    Main entry: runs initial solve, dichotomy, optional backward search,
    filters and returns either the best solution or full Pareto front.
    """
    log.info("=== solve_asap: START ===")
    log.info(
        "return_pareto_front=%s, pareto_front_more_solution=%s",
        problem["return_pareto_front"],
        problem["pareto_front_more_solution"],
    )
    log.debug("CLI args: %s", problem["cl_args"])

    # 1) initial solve
    init = solve(problem["instance"], problem["cl_args"])
    log.info(
        "initial solve: code=%s unassigned=%s",
        init.get("code"),
        init["summary"].get("unassigned"),
    )
    if init.get("code", 1) != 0:
        raise OSError(init["code"], init["error"])
    if init["summary"].get("unassigned", 0) != 0:
        raise OSError(2, "Initial solution has unassigned jobs")

    # 2) dichotomic horizon reduction
    solutions = dichotomy(problem["instance"], problem["cl_args"], init)

    # 3) backward search for extra points
    if problem["pareto_front_more_solution"]:
        solutions += backward_search(problem["instance"], problem["cl_args"], init)

    # 4) filter and sort
    solutions.sort(key=lambda s: max(r["steps"][-1]["arrival"] for r in s["routes"]))
    filter_dominated(solutions)
    filter_unique(solutions)

    # 5) optional plot
    if problem["pareto_plot_file"]:
        indicators = [
            {
                "completion": max(r["steps"][-1]["arrival"] for r in sol["routes"]),
                "cost": sol["summary"]["cost"],
                "origin": sol["origin"],
            }
            for sol in solutions
        ]
        plot_pareto_front(indicators, problem["pareto_plot_file"])

    # 6) return
    if problem["return_pareto_front"]:
        log.info(
            "solve_asap: returning full Pareto front (%d solutions)", len(solutions)
        )
        # strip origins
        for sol in solutions:
            sol.pop("origin", None)
        return solutions
    else:
        best = solutions[0]
        log.info(
            "solve_asap: returning best solution completion=%s cost=%s",
            max(r["steps"][-1]["arrival"] for r in best["routes"]),
            best["summary"]["cost"],
        )
        best.pop("origin", None)
        best["summary"].pop("computing_times", None)
        return best

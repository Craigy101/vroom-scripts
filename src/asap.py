#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
ASAP wrapper for VROOM with verbose logging.

* Logs every CLI flag that is forwarded to the inner solver.
* Prints the config file path if one is supplied.
* Emits progress information from solve_asap.
Logging goes to **stderr** so the JSON solution on **stdout**
remains clean.

Grant Fullston – May 2025
"""
import argparse
import json
import logging
import os
import sys
from utils.asap_helpers import solve_asap
from utils.matrix import add_matrix

# ── Logging setup ────────────────────────────────────────────────
LOG_LEVEL = os.getenv("ASAP_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("asap")


# ── Helper functions ─────────────────────────────────────────────
def get_cl_args(args, unknown_cli):
    """Re-build the CLI we’ll forward to the C++ solver."""
    all_args = []
    if args.a:
        all_args += ["-a" + a[0] for a in args.a]
    if args.g:
        all_args.append("-g")
    if args.l is not None:
        all_args.append("-l" + str(args.l))
    if args.p:
        all_args += ["-p" + p[0] for p in args.p]
    if args.r:
        all_args.append("-r" + args.r)
    if args.t is not None:
        all_args.append("-t" + str(args.t))
    if args.x is not None:
        all_args.append("-x" + str(args.x))

    # Forward any unrecognised flags untouched
    all_args.extend(unknown_cli)
    return all_args


def get_routing(args):
    routing = {"engine": args.r, "profiles": {}}
    if args.a:
        for a in args.a:
            profile, host = a[0].split(":")
            routing["profiles"].setdefault(profile, {})["host"] = host
    if args.p:
        for p in args.p:
            profile, port = p[0].split(":")
            routing["profiles"].setdefault(profile, {})["port"] = port
    if not routing["profiles"]:
        routing["profiles"] = {"car": {"host": "0.0.0.0", "port": "5000"}}
    return routing


if __name__ == "__main__":

    # ── Argument parsing ────────────────────────────────────────────
    parser = argparse.ArgumentParser(
        description="ASAP-minimising wrapper around vroom",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("-a", metavar="PROFILE:HOST", nargs="+", action="append")
    parser.add_argument("-g", action="store_true", help="add detailed geometry")
    parser.add_argument("-i", metavar="FILE", type=argparse.FileType("r"), default="-")
    parser.add_argument("-l", metavar="LIMIT", type=float)
    parser.add_argument(
        "-o", metavar="OUTPUT", type=argparse.FileType("w"), default="-"
    )
    parser.add_argument("-p", metavar="PROFILE:PORT", nargs="+", action="append")
    parser.add_argument("--pareto-front", action="store_true")
    parser.add_argument("--pareto-front-more-solutions", action="store_true")
    parser.add_argument("--pareto-plot-file", metavar="PNG/SVG file", default="")
    parser.add_argument("-r", metavar="ROUTER", default="osrm")
    parser.add_argument("-t", metavar="THREADS", type=int, default=4)
    parser.add_argument("-x", metavar="EXPLORE", type=int, default=5)

    # Let argparse keep *unknown* flags for pass-through
    known, unknown = parser.parse_known_args()
    args = known

    log.info("Known CLI args  : %s", vars(args))
    log.info("Unknown CLI args: %s", unknown)

    # Report which config file (if any) is supplied
    if "-c" in unknown:
        cfg_path = unknown[unknown.index("-c") + 1]
        log.info("Using config file: %s", cfg_path)
    elif any(tok.startswith("-c") and len(tok) > 2 for tok in unknown):
        # Handles merged form -c/path/to/config.yml
        cfg_path = [tok[2:] for tok in unknown if tok.startswith("-c")][0]
        log.info("Using config file: %s", cfg_path)

    # ── Main execution ──────────────────────────────────────────────
    try:
        data = json.load(args.i)
        if "matrices" not in data:
            log.info("Embedding distance matrix …")
            add_matrix(data, get_routing(args))
        else:
            log.info("GOOD - Using pre computed matrix …")

        cl_args = get_cl_args(args, unknown)
        log.info("CHECK - Forwarded CLI to core solver: %s", cl_args)

        response = solve_asap(
            {
                "instance": data,
                "return_pareto_front": args.pareto_front
                or args.pareto_front_more_solutions,
                "pareto_front_more_solution": args.pareto_front_more_solutions,
                "cl_args": cl_args,
                "pareto_plot_file": args.pareto_plot_file,
            }
        )
        log.info("Solve finished – status code %s", response.get("code", 0))
    except Exception as exc:  # broad catch to ensure JSON error output
        log.exception("ASAP wrapper failed:")
        response = {"code": 1, "error": str(exc)}

    json.dump(response, args.o)
    sys.exit(response.get("code", 0))

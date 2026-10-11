"""Unified CLI entrypoint for pipeline steps."""

from __future__ import annotations

import argparse

from src import __version__


def build_parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="python -m src.cli",
        description="Human disease → target pipeline (incremental).",
    )
    root.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = root.add_subparsers(dest="command", required=True)

    p1 = sub.add_parser("step1", help="Input disease / subtype / tissue + resolve ontology id")
    p1.add_argument("--disease", required=True)
    p1.add_argument("--subtype", default=None)
    p1.add_argument("--tissue", default=None)
    p1.add_argument("--disease-id", default=None)
    p1.add_argument("--run-id", default=None)
    p1.set_defaults(_handler="step1")

    p2 = sub.add_parser("step2", help="Collect disease–gene associations from databases")
    p2.add_argument("--run-id", required=True)
    p2.add_argument(
        "--skip-literature",
        action="store_true",
        help="Open Targets only (skip Europe PMC + TF-IDF literature RAG)",
    )
    p2.set_defaults(_handler="step2")

    pa1 = sub.add_parser("stepA1", help="Track A / Step A1 saturation analysis")
    pa1.add_argument("--run-id", required=True)
    pa1.set_defaults(_handler="stepA1")

    pa2 = sub.add_parser("stepA2", help="Track A / Step A2 downweight crowded targets")
    pa2.add_argument("--run-id", required=True)
    pa2.set_defaults(_handler="stepA2")

    pa3 = sub.add_parser("stepA3", help="Track A / Step A3 biological relevance")
    pa3.add_argument("--run-id", required=True)
    pa3.set_defaults(_handler="stepA3")

    pa4 = sub.add_parser("stepA4", help="Track A / Step A4 CADD readiness")
    pa4.add_argument("--run-id", required=True)
    pa4.set_defaults(_handler="stepA4")

    pa5 = sub.add_parser("stepA5", help="Track A / Step A5 final ranking")
    pa5.add_argument("--run-id", required=True)
    pa5.set_defaults(_handler="stepA5")

    pta = sub.add_parser("trackA", help="Run Track A end-to-end (A1..A5)")
    pta.add_argument("--run-id", required=True)
    pta.set_defaults(_handler="trackA")

    for step in ("B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B9", "B10"):
        pb = sub.add_parser(f"step{step}", help=f"Track B / Step {step}")
        pb.add_argument("--run-id", required=True)
        pb.set_defaults(_handler=f"step{step}")

    ptb = sub.add_parser("trackB", help="Run Track B end-to-end (B1..B10)")
    ptb.add_argument("--run-id", required=True)
    ptb.set_defaults(_handler="trackB")

    pf1 = sub.add_parser("stepF1", help="Fusion F1 — unified target portfolio (Track A + B)")
    pf1.add_argument("--run-id", required=True)
    pf1.set_defaults(_handler="stepF1")

    return root


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args._handler == "step1":
        from src.step01_input import run_step1
        from src.lib.models import RunInput

        inp = RunInput(
            disease_label=args.disease,
            disease_subtype=args.subtype,
            tissue=args.tissue,
            species="human",
        )
        from src.lib.paths import manifest_path

        manifest = run_step1(inp, disease_id_override=args.disease_id, run_id=args.run_id)
        print(f"run_id={manifest.run_id}")
        print(
            "selected_disease="
            f"{manifest.disease_resolution.selected.id} {manifest.disease_resolution.selected.name}"
        )
        if manifest.disease_resolution.note:
            print(f"note={manifest.disease_resolution.note}")
        print(f"wrote {manifest_path(manifest.run_id)}")
    elif args._handler == "step2":
        from src.step02_collect import run_step2

        run_step2(args.run_id, skip_literature=args.skip_literature)
    elif args._handler == "stepA1":
        from src.stepA1_saturation import run_step_a1

        run_step_a1(args.run_id)
    elif args._handler == "stepA2":
        from src.stepA2_downweight import run_step_a2

        run_step_a2(args.run_id)
    elif args._handler == "stepA3":
        from src.stepA3_relevance import run_step_a3

        run_step_a3(args.run_id)
    elif args._handler == "stepA4":
        from src.stepA4_cadd_readiness import run_step_a4

        run_step_a4(args.run_id)
    elif args._handler == "stepA5":
        from src.stepA5_rank import run_step_a5

        run_step_a5(args.run_id)
    elif args._handler == "trackA":
        from src.stepA_run_all import run_track_a

        run_track_a(args.run_id)
    elif args._handler == "stepB1":
        from src.stepB1_seed_expansion import run_step_b1

        run_step_b1(args.run_id)
    elif args._handler == "stepB2":
        from src.stepB2_functional_similarity import run_step_b2

        run_step_b2(args.run_id)
    elif args._handler == "stepB3":
        from src.stepB3_coexpression import run_step_b3

        run_step_b3(args.run_id)
    elif args._handler == "stepB4":
        from src.stepB4_differential_expression import run_step_b4

        run_step_b4(args.run_id)
    elif args._handler == "stepB5":
        from src.stepB5_pathway import run_step_b5

        run_step_b5(args.run_id)
    elif args._handler == "stepB6":
        from src.stepB6_genetic_support import run_step_b6

        run_step_b6(args.run_id)
    elif args._handler == "stepB7":
        from src.stepB7_network_prioritization import run_step_b7

        run_step_b7(args.run_id)
    elif args._handler == "stepB8":
        from src.stepB8_novelty import run_step_b8

        run_step_b8(args.run_id)
    elif args._handler == "stepB9":
        from src.stepB9_safety_druggability import run_step_b9

        run_step_b9(args.run_id)
    elif args._handler == "stepB10":
        from src.stepB10_rank import run_step_b10

        run_step_b10(args.run_id)
    elif args._handler == "trackB":
        from src.stepB_run_all import run_track_b

        run_track_b(args.run_id)
    elif args._handler == "stepF1":
        from src.stepF1_fusion import run_step_f1

        run_step_f1(args.run_id)
    else:
        raise AssertionError("unknown command")


if __name__ == "__main__":
    main()

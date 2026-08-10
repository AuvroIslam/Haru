"""Command line entry point.

The first distribution path is ``pip install haru`` followed by ``haru serve``,
which is how comparable tools ship (browser-use, ApplyPilot, AIHawk all start
as a package with a CLI). A desktop bundle wraps the same server later.

Everything defaults to the user's own machine: the Brain lives under
``~/.haru``, the server binds to loopback only, and no network call is made
unless the user configures a cloud model.
"""

from __future__ import annotations

import argparse
import os
import sys
import webbrowser
from pathlib import Path

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8731


def data_dir() -> Path:
    """Where the Brain and vault live. Overridable for testing and portability."""
    override = os.environ.get("HARU_HOME")
    return Path(override) if override else Path.home() / ".haru"


def brain_path() -> Path:
    return data_dir() / "brain.sqlite"


def vault_path() -> Path:
    return data_dir() / "vault"


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    from haru.api.app import create_app
    from haru.brain.store import BrainStore
    from haru.validation.validator import install

    path = Path(args.brain) if args.brain else brain_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    store = BrainStore(path)

    # Bind loopback by default. Binding publicly would expose a passport number
    # to the local network, so it takes an explicit flag and says so.
    host = args.host
    if host not in ("127.0.0.1", "localhost", "::1"):
        print(
            f"warning: binding to {host} exposes your Brain to the network. "
            "Use 127.0.0.1 unless you mean it.",
            file=sys.stderr,
        )

    if not args.no_validator:
        install()

    app = create_app(store=store)
    url = f"http://{host}:{args.port}"
    print(f"Haru — {url}")
    print(f"Brain: {path}")
    if args.no_validator:
        print("WARNING: validator disabled; nothing can be submitted.", file=sys.stderr)

    if args.open:
        webbrowser.open(url)

    uvicorn.run(app, host=host, port=args.port, log_level=args.log_level)
    return 0


def _status(args: argparse.Namespace) -> int:
    from haru.brain.fact_boundary import derive
    from haru.brain.review import ReviewQueue
    from haru.brain.store import BrainStore

    path = Path(args.brain) if args.brain else brain_path()
    if not path.exists():
        print(f"No Brain at {path}. Run `haru serve` to create one.")
        return 1

    store = BrainStore(path)
    counts = store.counts()
    boundary = derive(store)
    pending = ReviewQueue(store).count()

    print(f"Brain:   {path}")
    print(f"Records: {sum(counts.values())} " + (f"({counts})" if counts else ""))
    print(f"Pending review: {pending}")
    print(f"Claimable skills: {len(boundary.allowed_skills)}")
    print(f"Claimable credentials: {len(boundary.claimable_credentials)}")
    if boundary.is_empty:
        print("\nThe fact boundary is empty — nothing can be claimed yet.")
        print("Confirm some facts before generating anything.")
    store.close()
    return 0


def _export(args: argparse.Namespace) -> int:
    from haru.brain.portable import write_export
    from haru.brain.store import BrainStore

    path = Path(args.brain) if args.brain else brain_path()
    if not path.exists():
        print(f"No Brain at {path}.", file=sys.stderr)
        return 1

    store = BrainStore(path)
    target = write_export(store, args.output, profile_id=None, redact=args.redact)
    store.close()
    print(f"Exported to {target}" + (" (redacted)" if args.redact else ""))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="haru",
        description="Your facts and documents, carried onto any form on the web.",
    )
    parser.add_argument("--brain", help="path to the Brain database")

    # Accept --brain on either side of the subcommand. `haru status --brain X`
    # is what people actually type; SUPPRESS keeps the subparser from
    # overwriting a value given before the subcommand with its own default.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--brain", help="path to the Brain database", default=argparse.SUPPRESS
    )

    sub = parser.add_subparsers(dest="command", parser_class=argparse.ArgumentParser)

    serve = sub.add_parser("serve", parents=[common], help="start the local control panel")
    serve.add_argument("--host", default=DEFAULT_HOST)
    serve.add_argument("--port", type=int, default=DEFAULT_PORT)
    serve.add_argument("--open", action="store_true", help="open a browser")
    serve.add_argument("--log-level", default="info")
    serve.add_argument(
        "--no-validator",
        action="store_true",
        help="run without the fact-boundary validator (blocks all submission)",
    )
    serve.set_defaults(func=_serve)

    status = sub.add_parser("status", parents=[common], help="summarise the Brain")
    status.set_defaults(func=_status)

    export = sub.add_parser("export", parents=[common], help="write the Brain out as JSON")
    export.add_argument("output", help="destination file")
    export.add_argument("--redact", action="store_true", help="strip sensitive fields")
    export.set_defaults(func=_export)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

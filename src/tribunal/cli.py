import json
import shlex
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from tribunal import __version__
from tribunal.config import get_settings
from tribunal.gitutil import GitError
from tribunal.ledger import compute_trust
from tribunal.llm import LLMError
from tribunal.models import SignedReceipt, Verdict
from tribunal.pipeline import PipelineError, SubmissionError, build_pipeline
from tribunal.receipts import ReceiptSigner, verify_receipt
from tribunal.sandbox import SandboxUnavailableError, WorkspaceError
from tribunal.store import Store
from tribunal.summary import render_text

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Adversarial verification for AI-written code.",
)

EXIT_CODES = {Verdict.PASS: 0, Verdict.FAIL: 1, Verdict.INCONCLUSIVE: 2}
EXIT_ERROR = 3


def _fail(message: str) -> NoReturn:
    typer.echo(f"error: {message}", err=True)
    raise typer.Exit(EXIT_ERROR)


def _open_store() -> Store:
    settings = get_settings()
    settings.ensure_dirs()
    return Store(settings.db_path)


def _local_public_key() -> str | None:
    settings = get_settings()
    if not settings.key_path.exists():
        return None
    return ReceiptSigner.load_or_create(settings.key_path).public_key_b64


@app.command()
def version() -> None:
    typer.echo(__version__)


@app.command()
def submit(
    repo_path: Annotated[Path, typer.Option("--repo-path", help="Local git repository")] = Path("."),
    base: Annotated[str, typer.Option(help="Base ref")] = "HEAD~1",
    head: Annotated[str, typer.Option(help="Head ref")] = "HEAD",
    title: Annotated[str, typer.Option(help="PR title")] = "",
    description: Annotated[str, typer.Option(help="PR description")] = "",
    agent: Annotated[str, typer.Option(help="Name of the agent that wrote the change")] = "unknown",
    repo: Annotated[str | None, typer.Option(help="Repository name")] = None,
    test_cmd: Annotated[str | None, typer.Option("--test-cmd", help="Test command")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Print the signed receipt")] = False,
) -> None:
    try:
        pipeline = build_pipeline()
        submission = pipeline.submit(
            repo_path=repo_path,
            base=base,
            head=head,
            repo=repo,
            title=title,
            description=description,
            agent=agent,
            test_command=shlex.split(test_cmd) if test_cmd else [],
        )
        receipt = pipeline.run(submission.id)
    except (
        SubmissionError,
        PipelineError,
        LLMError,
        SandboxUnavailableError,
        WorkspaceError,
        GitError,
    ) as exc:
        _fail(str(exc))

    typer.echo(receipt.model_dump_json(indent=2) if as_json else render_text(receipt))
    raise typer.Exit(EXIT_CODES[receipt.body.verdict])


@app.command()
def verdict(
    submission_id: Annotated[str, typer.Argument()],
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    store = _open_store()
    submission = store.get_submission(submission_id)
    if submission is None:
        _fail(f"unknown submission {submission_id}")
    receipt = store.latest_receipt_for(submission_id)
    if receipt is None:
        typer.echo(f"status: {submission.status.value}")
        raise typer.Exit(EXIT_ERROR)
    typer.echo(receipt.model_dump_json(indent=2) if as_json else render_text(receipt))
    raise typer.Exit(EXIT_CODES[receipt.body.verdict])


@app.command("verify-receipt")
def verify_receipt_cmd(
    target: Annotated[str, typer.Argument(help="Receipt JSON file or receipt id")],
    public_key: Annotated[str | None, typer.Option("--public-key", help="Expected key")] = None,
) -> None:
    path = Path(target)
    if path.is_file():
        try:
            receipt = SignedReceipt.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            _fail(f"cannot read receipt: {exc}")
    else:
        found = _open_store().get_receipt(target)
        if found is None:
            _fail(f"unknown receipt {target}")
        receipt = found

    expected = public_key or _local_public_key()
    intact = verify_receipt(receipt)
    signer_ok = expected is None or receipt.public_key == expected

    typer.echo(f"integrity: {'valid' if intact else 'INVALID'}")
    if expected is None:
        typer.echo("signer: not checked")
    else:
        typer.echo(f"signer: {'matches expected key' if signer_ok else 'DIFFERENT from expected key'}")
    typer.echo(f"verdict: {receipt.body.verdict.value}  head: {receipt.body.head_sha[:12]}")
    raise typer.Exit(0 if intact and signer_ok else 1)


@app.command()
def trust(
    agent: Annotated[str, typer.Argument()],
    repo: Annotated[str | None, typer.Option(help="Limit to one repository")] = None,
) -> None:
    result = compute_trust(_open_store(), agent, repo)
    typer.echo(json.dumps(result.model_dump(), indent=2))


@app.command("public-key")
def public_key_cmd() -> None:
    settings = get_settings()
    settings.ensure_dirs()
    typer.echo(ReceiptSigner.load_or_create(settings.key_path).public_key_b64)


@app.command()
def serve(
    host: Annotated[str | None, typer.Option(help="Bind host")] = None,
    port: Annotated[int | None, typer.Option(help="Bind port")] = None,
) -> None:
    import uvicorn

    from tribunal.api import create_app

    settings = get_settings()
    uvicorn.run(
        create_app(settings=settings),
        host=host or settings.api_host,
        port=port or settings.api_port,
    )


@app.command("mcp")
def mcp_cmd() -> None:
    from tribunal.mcp_server import create_server

    create_server().run()

import json
import os
import shlex
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from tribunal import __version__
from tribunal.ci import CIError, load_pr_context, upsert_comment, write_outputs, write_step_summary
from tribunal.config import get_settings
from tribunal.gitutil import GitError, merge_base
from tribunal.ledger import compute_trust
from tribunal.llm import LLMError
from tribunal.models import SignedReceipt, Verdict
from tribunal.pipeline import PipelineError, SubmissionError, build_pipeline
from tribunal.receipts import ReceiptSigner, verify_receipt
from tribunal.sandbox import SandboxUnavailableError, WorkspaceError
from tribunal.store import Store
from tribunal.summary import render_markdown, render_text

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Adversarial verification for AI-written code.",
)

EXIT_CODES = {Verdict.PASS: 0, Verdict.FAIL: 1, Verdict.INCONCLUSIVE: 2}
EXIT_ERROR = 3

HANDLED = (
    CIError,
    GitError,
    LLMError,
    PipelineError,
    SandboxUnavailableError,
    SubmissionError,
    WorkspaceError,
)


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
    repo_path: Annotated[Path, typer.Option("--repo-path", help="Local git repo")] = Path("."),
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
    except HANDLED as exc:
        _fail(str(exc))

    typer.echo(receipt.model_dump_json(indent=2) if as_json else render_text(receipt))
    raise typer.Exit(EXIT_CODES[receipt.body.verdict])


@app.command("ci")
def ci_cmd(
    repo_path: Annotated[Path, typer.Option("--repo-path", help="Repository checkout")] = Path("."),
    test_cmd: Annotated[
        str | None,
        typer.Option("--test-cmd", envvar="TRIBUNAL_TEST_COMMAND", help="Test command"),
    ] = None,
    agent: Annotated[
        str | None,
        typer.Option(envvar="TRIBUNAL_AGENT", help="Agent name, defaults to the PR author"),
    ] = None,
    comment: Annotated[
        bool,
        typer.Option("--comment/--no-comment", envvar="TRIBUNAL_COMMENT", help="Post a PR comment"),
    ] = True,
    fail_on: Annotated[
        str,
        typer.Option(envvar="TRIBUNAL_FAIL_ON", help="Fail the job on 'fail' or 'inconclusive'"),
    ] = "fail",
    receipt_out: Annotated[
        Path | None,
        typer.Option("--receipt-out", envvar="TRIBUNAL_RECEIPT_OUT", help="Write receipt JSON"),
    ] = None,
) -> None:
    if fail_on not in {"fail", "inconclusive"}:
        _fail("--fail-on must be 'fail' or 'inconclusive'")
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path:
        _fail("GITHUB_EVENT_PATH is not set; run this inside GitHub Actions")

    try:
        context = load_pr_context(event_path)
        base = merge_base(repo_path, context.base_sha, context.head_sha)
        pipeline = build_pipeline()
        submission = pipeline.submit(
            repo_path=repo_path,
            base=base,
            head=context.head_sha,
            repo=context.repo,
            title=context.title,
            description=context.body,
            agent=agent or context.author,
            test_command=shlex.split(test_cmd) if test_cmd else [],
        )
        receipt = pipeline.run(submission.id)
    except HANDLED as exc:
        _fail(str(exc))

    markdown = render_markdown(receipt)
    write_step_summary(markdown)
    write_outputs(receipt)
    if receipt_out is not None:
        receipt_out.parent.mkdir(parents=True, exist_ok=True)
        receipt_out.write_text(receipt.model_dump_json(indent=2), encoding="utf-8")
    typer.echo(render_text(receipt))

    if comment:
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            typer.echo("warning: GITHUB_TOKEN is not set, skipping comment", err=True)
        else:
            try:
                typer.echo(
                    f"comment: {upsert_comment(context.repo, context.number, token, markdown)}"
                )
            except CIError as exc:
                typer.echo(f"warning: {exc}", err=True)

    verdict = receipt.body.verdict
    if verdict is Verdict.FAIL:
        raise typer.Exit(EXIT_CODES[Verdict.FAIL])
    if verdict is Verdict.INCONCLUSIVE and fail_on == "inconclusive":
        raise typer.Exit(EXIT_CODES[Verdict.INCONCLUSIVE])
    raise typer.Exit(0)


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

    if expected is None:
        signer_text = "not checked"
    elif signer_ok:
        signer_text = "matches expected key"
    else:
        signer_text = "DIFFERENT from expected key"

    typer.echo(f"integrity: {'valid' if intact else 'INVALID'}")
    typer.echo(f"signer: {signer_text}")
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

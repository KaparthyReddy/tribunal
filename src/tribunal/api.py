import logging
import secrets
import threading

from fastapi import APIRouter, BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

from tribunal import __version__
from tribunal.config import Settings, get_settings
from tribunal.ledger import AgentTrust, compute_trust
from tribunal.llm import LLMError
from tribunal.models import SignedReceipt, Submission, SubmissionStatus
from tribunal.pipeline import Pipeline, SubmissionError, build_pipeline
from tribunal.receipts import verify_receipt
from tribunal.sandbox import SandboxUnavailableError

log = logging.getLogger(__name__)


class SubmitRequest(BaseModel):
    repo_path: str
    base: str
    head: str = "HEAD"
    repo: str | None = None
    title: str = ""
    description: str = ""
    agent: str = "unknown"
    test_command: list[str] = Field(default_factory=list)
    wait: bool = False


class SubmitResponse(BaseModel):
    submission_id: str
    status: SubmissionStatus
    receipt: SignedReceipt | None = None


class VerifyResponse(BaseModel):
    intact: bool
    trusted: bool


def _run_background(pipeline: Pipeline, submission_id: str) -> None:
    try:
        pipeline.run(submission_id)
    except Exception:
        log.exception("background verification failed for %s", submission_id)


def create_app(pipeline: Pipeline | None = None, settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="Tribunal", version=__version__)
    state: dict[str, Pipeline | None] = {"pipeline": pipeline}
    lock = threading.Lock()

    def get_pipeline() -> Pipeline:
        with lock:
            current = state["pipeline"]
            if current is None:
                current = build_pipeline(settings)
                state["pipeline"] = current
            return current

    def require_auth(authorization: str | None = Header(default=None)) -> None:
        token = settings.api_token
        if not token:
            return
        supplied = (authorization or "").removeprefix("Bearer ").strip()
        if not secrets.compare_digest(supplied.encode(), token.encode()):
            raise HTTPException(status_code=401, detail="invalid token")

    router = APIRouter(dependencies=[Depends(require_auth)])

    @router.post("/submissions", response_model=SubmitResponse)
    def submit(request: SubmitRequest, background: BackgroundTasks) -> SubmitResponse:
        pipe = get_pipeline()
        try:
            submission = pipe.submit(
                repo_path=request.repo_path,
                base=request.base,
                head=request.head,
                repo=request.repo,
                title=request.title,
                description=request.description,
                agent=request.agent,
                test_command=request.test_command,
            )
        except SubmissionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        if not request.wait:
            background.add_task(_run_background, pipe, submission.id)
            return SubmitResponse(submission_id=submission.id, status=submission.status)

        try:
            receipt = pipe.run(submission.id)
        except (SandboxUnavailableError, LLMError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            log.exception("verification failed for %s", submission.id)
            raise HTTPException(status_code=500, detail=f"verification failed: {exc}") from exc
        return SubmitResponse(
            submission_id=submission.id,
            status=SubmissionStatus.COMPLETE,
            receipt=receipt,
        )

    @router.get("/submissions", response_model=list[Submission])
    def list_submissions(
        limit: int = Query(default=50, ge=1, le=200),
        repo: str | None = None,
    ) -> list[Submission]:
        return get_pipeline().store.list_submissions(limit=limit, repo=repo)

    @router.get("/submissions/{submission_id}", response_model=Submission)
    def get_submission(submission_id: str) -> Submission:
        submission = get_pipeline().store.get_submission(submission_id)
        if submission is None:
            raise HTTPException(status_code=404, detail="unknown submission")
        return submission

    @router.get("/submissions/{submission_id}/receipt", response_model=SignedReceipt)
    def get_submission_receipt(submission_id: str) -> SignedReceipt:
        receipt = get_pipeline().store.latest_receipt_for(submission_id)
        if receipt is None:
            raise HTTPException(status_code=404, detail="no receipt for this submission")
        return receipt

    @router.get("/receipts/{receipt_id}", response_model=SignedReceipt)
    def get_receipt(receipt_id: str) -> SignedReceipt:
        receipt = get_pipeline().store.get_receipt(receipt_id)
        if receipt is None:
            raise HTTPException(status_code=404, detail="unknown receipt")
        return receipt

    @router.post("/receipts/verify", response_model=VerifyResponse)
    def verify(receipt: SignedReceipt) -> VerifyResponse:
        signer = get_pipeline().signer
        return VerifyResponse(
            intact=verify_receipt(receipt),
            trusted=receipt.public_key == signer.public_key_b64,
        )

    @router.get("/agents/{agent}/trust", response_model=AgentTrust)
    def agent_trust(agent: str, repo: str | None = None) -> AgentTrust:
        return compute_trust(get_pipeline().store, agent, repo)

    @router.get("/public-key")
    def public_key() -> dict[str, str]:
        return {"public_key": get_pipeline().signer.public_key_b64}

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    app.include_router(router)
    return app

"""FastAPI service for debugging HTTP content negotiation."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .negotiation import (
    AcceptSyntaxError,
    CandidateMediaTypeError,
    best_match,
    parse_accept,
    parse_concrete_media_type,
)

app = FastAPI(
    title="HTTP Content Negotiation Debugger",
    version="1.0.0",
    description=(
        "POST an Accept header string plus a list of candidate "
        "representations to /negotiate and inspect which representation "
        "would be selected and why the others lost."
    ),
)


class CandidateIn(BaseModel):
    media_type: str = Field(
        ..., description="Concrete media type, e.g. application/json",
        examples=["application/json"],
    )
    server_priority: float = Field(
        0, description="Server-side preference; higher wins ties."
    )


class NegotiateRequest(BaseModel):
    accept: str = Field(
        ...,
        description="Accept header value: type/subtype, type/* or */* "
        "ranges with optional q (no media parameters).",
        examples=["text/*;q=0.8, application/json;q=0.9, */*;q=0.1"],
    )
    candidates: list[CandidateIn] = Field(default_factory=list)


class AcceptRangeReport(BaseModel):
    range: str
    q: float
    specificity: int
    position: int


class CandidateReport(BaseModel):
    index: int
    media_type: str
    server_priority: float
    matched_range: str | None
    q: float | None
    specificity: int | None
    eliminated: bool
    elimination_reason: str | None


class SelectedReport(BaseModel):
    index: int
    media_type: str
    server_priority: float
    matched_range: str
    q: float
    specificity: int


class NegotiateResponse(BaseModel):
    selected: SelectedReport | None
    accept_ranges: list[AcceptRangeReport]
    candidates: list[CandidateReport]


@app.get("/")
def root() -> dict:
    return {
        "service": "http-content-negotiation-debugger",
        "usage": (
            "POST /negotiate with JSON body "
            "{'accept': <Accept header string>, 'candidates': "
            "[{'media_type': 'type/subtype', 'server_priority': <number>}]}"
        ),
        "docs": "/docs",
    }


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.post(
    "/negotiate",
    response_model=NegotiateResponse,
    responses={
        400: {"description": "Invalid Accept syntax or non-concrete candidate media type"},
        406: {"model": NegotiateResponse, "description": "No candidate survived negotiation"},
    },
)
def negotiate(req: NegotiateRequest) -> NegotiateResponse | JSONResponse:
    try:
        ranges = parse_accept(req.accept)
    except AcceptSyntaxError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    reports: list[CandidateReport] = []
    for index, candidate in enumerate(req.candidates):
        try:
            ctype, csubtype = parse_concrete_media_type(candidate.media_type)
        except CandidateMediaTypeError as exc:
            raise HTTPException(
                status_code=400, detail=f"candidates[{index}]: {exc}"
            ) from exc

        matched = best_match(ranges, ctype, csubtype)
        if matched is None:
            reports.append(
                CandidateReport(
                    index=index,
                    media_type=candidate.media_type,
                    server_priority=candidate.server_priority,
                    matched_range=None,
                    q=None,
                    specificity=None,
                    eliminated=True,
                    elimination_reason="no accept range matches this media type",
                )
            )
        elif matched.q == 0:
            reports.append(
                CandidateReport(
                    index=index,
                    media_type=candidate.media_type,
                    server_priority=candidate.server_priority,
                    matched_range=matched.range,
                    q=matched.q,
                    specificity=matched.specificity,
                    eliminated=True,
                    elimination_reason=(
                        f"matched range {matched.range!r} has q=0 "
                        "(explicitly refused)"
                    ),
                )
            )
        else:
            reports.append(
                CandidateReport(
                    index=index,
                    media_type=candidate.media_type,
                    server_priority=candidate.server_priority,
                    matched_range=matched.range,
                    q=matched.q,
                    specificity=matched.specificity,
                    eliminated=False,
                    elimination_reason=None,
                )
            )

    selected: SelectedReport | None = None
    available = [r for r in reports if not r.eliminated]
    if available:
        # Highest q, then highest specificity, then highest server_priority,
        # then lowest input index.
        winner = min(
            available,
            key=lambda r: (-r.q, -r.specificity, -r.server_priority, r.index),
        )
        selected = SelectedReport(
            index=winner.index,
            media_type=winner.media_type,
            server_priority=winner.server_priority,
            matched_range=winner.matched_range,  # type: ignore[arg-type]
            q=winner.q,  # type: ignore[arg-type]
            specificity=winner.specificity,  # type: ignore[arg-type]
        )

    payload = NegotiateResponse(
        selected=selected,
        accept_ranges=[
            AcceptRangeReport(
                range=r.range, q=r.q, specificity=r.specificity, position=r.position
            )
            for r in ranges
        ],
        candidates=reports,
    )
    if selected is None:
        return JSONResponse(status_code=406, content=payload.model_dump())
    return payload

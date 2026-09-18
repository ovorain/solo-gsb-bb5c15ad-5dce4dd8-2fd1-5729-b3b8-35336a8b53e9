"""Tests for the /negotiate endpoint and the negotiation engine."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def negotiate(accept, candidates):
    return client.post(
        "/negotiate", json={"accept": accept, "candidates": candidates}
    )


def cand(media_type, server_priority=0):
    return {"media_type": media_type, "server_priority": server_priority}


# --- happy path -----------------------------------------------------------


def test_exact_match_wins_over_wildcards():
    resp = negotiate(
        "text/*;q=0.8, application/json;q=0.9, */*;q=0.1",
        [cand("text/html", 10), cand("application/json", 20), cand("image/png", 30)],
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["selected"]["media_type"] == "application/json"
    assert body["selected"]["matched_range"] == "application/json"
    assert body["selected"]["q"] == 0.9
    assert body["selected"]["specificity"] == 2

    reports = {c["media_type"]: c for c in body["candidates"]}
    assert reports["text/html"]["matched_range"] == "text/*"
    assert reports["text/html"]["q"] == 0.8
    assert reports["text/html"]["specificity"] == 1
    assert reports["image/png"]["matched_range"] == "*/*"
    assert reports["image/png"]["specificity"] == 0


def test_q_defaults_to_one():
    resp = negotiate("application/json", [cand("application/json")])
    assert resp.status_code == 200
    assert resp.json()["selected"]["q"] == 1.0


def test_case_insensitive():
    resp = negotiate("Application/JSON;Q=0.5", [cand("APPLICATION/json")])
    assert resp.status_code == 200
    selected = resp.json()["selected"]
    assert selected["q"] == 0.5
    assert selected["matched_range"] == "application/json"


def test_most_specific_range_supplies_q():
    # text/html exact has lower q than text/*, but it is more specific.
    resp = negotiate("text/*;q=0.9, text/html;q=0.2", [cand("text/html")])
    report = resp.json()["candidates"][0]
    assert report["matched_range"] == "text/html"
    assert report["q"] == 0.2


def test_earliest_range_wins_specificity_tie():
    resp = negotiate("text/*;q=0.4, text/*;q=0.9", [cand("text/html")])
    report = resp.json()["candidates"][0]
    assert report["q"] == 0.4


def test_q_zero_excludes_candidate():
    resp = negotiate(
        "application/json;q=0, */*;q=0.5",
        [cand("application/json"), cand("text/html")],
    )
    body = resp.json()
    assert body["selected"]["media_type"] == "text/html"
    report = body["candidates"][0]
    assert report["eliminated"] is True
    assert report["q"] == 0.0
    assert "q=0" in report["elimination_reason"]


def test_specific_q_zero_beats_generic_nonzero():
    # The most specific match decides, even when it excludes the candidate.
    resp = negotiate("text/html;q=0, text/*;q=0.5", [cand("text/html")])
    assert resp.status_code == 406
    assert resp.json()["candidates"][0]["eliminated"] is True


# --- selection ordering ---------------------------------------------------


def test_ordering_q_then_specificity_then_priority_then_input_order():
    resp = negotiate(
        "text/*;q=0.5, application/json;q=0.5",
        [
            cand("text/html", 100),        # q .5 spec 1
            cand("application/json", 1),   # q .5 spec 2 -> wins on specificity
        ],
    )
    assert resp.json()["selected"]["media_type"] == "application/json"

    resp = negotiate(
        "text/*;q=0.5",
        [cand("text/html", 1), cand("text/plain", 2)],
    )
    assert resp.json()["selected"]["media_type"] == "text/plain"

    resp = negotiate(
        "text/*;q=0.5",
        [cand("text/html", 5), cand("text/plain", 5)],
    )
    assert resp.json()["selected"]["media_type"] == "text/html"  # input order


# --- 406 ------------------------------------------------------------------


def test_406_when_nothing_matches():
    resp = negotiate("text/html", [cand("application/json")])
    assert resp.status_code == 406
    body = resp.json()
    assert body["selected"] is None
    assert body["candidates"][0]["eliminated"] is True
    assert body["candidates"][0]["matched_range"] is None
    assert "no accept range" in body["candidates"][0]["elimination_reason"]


def test_406_when_candidate_list_empty():
    resp = negotiate("*/*", [])
    assert resp.status_code == 406
    assert resp.json()["selected"] is None


# --- 400: bad Accept syntax -----------------------------------------------


def test_400_on_media_parameters():
    resp = negotiate("text/html;level=1", [cand("text/html")])
    assert resp.status_code == 400


def test_400_on_bad_q_values():
    for accept in ["text/html;q=1.5", "text/html;q=abc", "text/html;q=0.1234",
                   "text/html;q", "text/html;q=0.5;q=0.6"]:
        resp = negotiate(accept, [cand("text/html")])
        assert resp.status_code == 400, accept


def test_400_on_malformed_ranges():
    for accept in ["", "   ", "text", "*/json", "text/", "/json",
                   "text/html,", "text/html,,application/json",
                   "text/htm l", "text/html;"]:
        resp = negotiate(accept, [cand("text/html")])
        assert resp.status_code == 400, accept


# --- 400: bad candidates ---------------------------------------------------


def test_400_on_non_concrete_candidate():
    for media_type in ["text/*", "*/*", "text", "application/json; charset=utf-8"]:
        resp = negotiate("*/*", [cand(media_type)])
        assert resp.status_code == 400, media_type


# --- misc ------------------------------------------------------------------


def test_healthz():
    assert client.get("/healthz").json() == {"status": "ok"}


def test_accept_ranges_echoed_for_debugging():
    body = negotiate("text/*;q=0.5, */*;q=0.1", [cand("text/html")]).json()
    assert body["accept_ranges"] == [
        {"range": "text/*", "q": 0.5, "specificity": 1, "position": 0},
        {"range": "*/*", "q": 0.1, "specificity": 0, "position": 1},
    ]

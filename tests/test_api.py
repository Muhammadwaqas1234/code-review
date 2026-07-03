"""API layer: endpoints, validation, and error mapping (no live LLM calls)."""

import glob
import os
import tempfile

from app.schemas.review import ReviewCategory


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_dashboard_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    assert 'id="reviewer-list"' in r.text


def test_static_assets(client):
    for asset in ("/static/css/style.css", "/static/js/app.js"):
        r = client.get(asset)
        assert r.status_code == 200 and len(r.text) > 500


def test_openapi_exposes_contract(client):
    spec = client.get("/openapi.json").json()
    assert "/api/review" in spec["paths"]
    assert "/api/reviewers" in spec["paths"]
    assert "ReviewResponse" in spec["components"]["schemas"]


def test_list_reviewers(client):
    r = client.get("/api/reviewers")
    assert r.status_code == 200
    data = r.json()
    assert {rv["id"] for rv in data} == {c.value for c in ReviewCategory}
    sec = next(rv for rv in data if rv["id"] == "security")
    assert sec["name"] == "Security" and len(sec["rules"]) >= 10


def test_non_pdf_rejected(client):
    r = client.post("/api/review",
                    data={"repo_url": "https://github.com/octocat/Hello-World"},
                    files={"roles_file": ("roles.txt", b"nope", "text/plain")})
    assert r.status_code == 400 and "PDF" in r.json()["detail"]


def test_bad_host_rejected(client, sample_pdf):
    r = client.post("/api/review",
                    data={"repo_url": "https://evil.example.com/a/b"},
                    files={"roles_file": ("roles.pdf", sample_pdf, "application/pdf")})
    assert r.status_code == 400


def test_corrupt_pdf_rejected(client):
    r = client.post("/api/review",
                    data={"repo_url": "https://github.com/octocat/Hello-World"},
                    files={"roles_file": ("roles.pdf", b"%PDF-1.4 garbage", "application/pdf")})
    assert r.status_code == 400 and "valid PDF" in r.json()["detail"]


def test_oversized_upload_rejected(client):
    big = b"%PDF-1.4" + b"0" * (11 * 1024 * 1024)
    r = client.post("/api/review",
                    data={"repo_url": "https://github.com/octocat/Hello-World"},
                    files={"roles_file": ("roles.pdf", big, "application/pdf")})
    assert r.status_code == 413


def test_unknown_reviewer_rejected(client, sample_pdf):
    r = client.post("/api/review",
                    data={"repo_url": "https://github.com/octocat/Hello-World",
                          "reviewers": "security,not-real"},
                    files={"roles_file": ("roles.pdf", sample_pdf, "application/pdf")})
    assert r.status_code == 400 and "Unknown reviewer" in r.json()["detail"]


def test_missing_repo_url_is_422(client, sample_pdf):
    r = client.post("/api/review",
                    files={"roles_file": ("roles.pdf", sample_pdf, "application/pdf")})
    assert r.status_code == 422


def test_pdf_is_optional_bad_url_still_reaches_url_check(client):
    # No roles_file at all: the request must pass PDF handling and fail only
    # on the (deliberately bad) URL — proving the PDF is not required.
    r = client.post("/api/review",
                    data={"repo_url": "https://evil.example.com/a/b"})
    assert r.status_code == 400
    assert "PDF" not in r.json()["detail"]  # failure is about the URL, not a missing PDF


def test_no_temp_files_leak_after_rejections(client):
    leaks = glob.glob(os.path.join(tempfile.gettempdir(), "code_review_roles_*"))
    assert not leaks, f"leaked temp uploads: {leaks}"

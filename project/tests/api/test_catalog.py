"""条款目录契约测试。"""

from __future__ import annotations


def test_clause_endpoint_returns_full_payload(api_client) -> None:
    response = api_client.get("/api/clause/GB 55031-2022_1.0.1")
    assert response.status_code == 200
    body = response.json()
    assert body["clause_no"] == "1.0.1"
    assert body["standard_id"] == "GB 55031-2022"
    assert body["text"]
    assert isinstance(body["kuans"], list)
    assert body["tables"] == []


def test_clause_endpoint_404(api_client) -> None:
    response = api_client.get("/api/clause/GB 9999-2025_1.0.1")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "clause_not_found"


def test_clauses_in_section(api_client) -> None:
    response = api_client.get(
        "/api/clauses", params={"standard_id": "GB 55031-2022", "section_no": "5.3"}
    )
    body = response.json()
    assert response.status_code == 200
    assert body["count"] == 12
    assert all(item["clause_no"].startswith("5.3.") for item in body["items"])


def test_clauses_requires_parameters(api_client) -> None:
    response = api_client.get("/api/clauses")
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "missing_parameter"


def test_standards_tree(api_client) -> None:
    body = api_client.get("/api/standards").json()
    assert len(body["items"]) == 3
    civil = next(item for item in body["items"] if item["standard_id"] == "GB 55031-2022")
    assert len(civil["chapters"]) == 6
    chapter_five = next(ch for ch in civil["chapters"] if ch["chapter_no"] == 5)
    section_53 = next(sec for sec in chapter_five["sections"] if sec["section_id"] == "5.3")
    assert section_53["clause_count"] == 12
    assert section_53["title"]


def test_search_returns_cross_standard_matches_and_filter(api_client) -> None:
    response = api_client.get("/api/search", params={"clause_no": "3.1.1"})
    body = response.json()
    assert body["count"] >= 2
    standard_ids = {item["standard_id"] for item in body["items"]}
    assert {"GB 55038-2025", "GB 55008-2021"} <= standard_ids
    filtered = api_client.get(
        "/api/search",
        params={"clause_no": "3.1.1", "standard_id": "GB 55008-2021"},
    ).json()
    assert filtered["count"] == 1
    assert filtered["items"][0]["standard_id"] == "GB 55008-2021"


def test_search_missing_clause_returns_empty(api_client) -> None:
    body = api_client.get("/api/search", params={"clause_no": "9.9.9"}).json()
    assert body["count"] == 0
    assert body["items"] == []

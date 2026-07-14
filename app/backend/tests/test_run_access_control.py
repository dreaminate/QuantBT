from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.main as main
import app.run_detail_core as run_detail_core
from app.auth import require_user_dependency
from app.auth import AuthService
from app.community import CommunityService
from app.community.compliance import ComplianceService
from app.ide import IDEError


class _NoIdeRuns:
    def get_run(self, run_id: str):  # noqa: ANN201
        raise IDEError(f"run not found: {run_id}")


@pytest.fixture
def run_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "runs"
    root.mkdir()
    monkeypatch.setattr(run_detail_core, "RUN_ROOT", root)
    monkeypatch.setattr(main, "RUN_ROOT", root)
    monkeypatch.setattr(main, "IDE_SERVICE", _NoIdeRuns())
    return root


@pytest.fixture
def client():  # noqa: ANN201
    try:
        yield TestClient(main.app)
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def _as_user(user_id: str, username: str | None = None) -> None:
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id=user_id,
        username=username or user_id,
    )


def _write_run(
    root: Path,
    run_id: str,
    *,
    owner_user_id: str | None = None,
    owner_username: str | None = None,
    nested_owner: bool = False,
    market: str = "test-market",
) -> Path:
    directory = root / run_id
    directory.mkdir()
    manifest: dict[str, object] = {
        "run_id": run_id,
        "strategy_name": run_id,
        "started_at": "2026-07-12T00:00:00Z",
        "market": market,
        "metrics": {"sharpe": 1.0},
    }
    owner_fields = {
        key: value
        for key, value in {
            "owner_user_id": owner_user_id,
            "owner_username": owner_username,
        }.items()
        if value is not None
    }
    if nested_owner:
        manifest["source"] = {"kind": "ide_sandbox", **owner_fields}
    else:
        manifest.update(owner_fields)
    (directory / "run.json").write_text(json.dumps(manifest), encoding="utf-8")
    (directory / "report.md").write_text(f"PRIVATE:{run_id}", encoding="utf-8")
    (directory / "portfolio.csv").write_text(
        "timestamp,equity,net_return,drawdown\n2026-07-12,1.0,0.0,0.0\n",
        encoding="utf-8",
    )
    return directory


@pytest.mark.parametrize(
    ("method", "path", "json_body"),
    (
        ("get", "/api/runs", None),
        ("post", "/api/runs/query", {}),
        ("get", "/api/runs/compare?run_ids=private-run", None),
        ("get", "/api/runs/compare_legacy?run_ids=private-run", None),
        ("get", "/api/runs/compare/series?run_ids=private-run&series=equity", None),
        ("get", "/api/runs/private-run", None),
        ("get", "/api/runs/private-run/series?series=equity", None),
        ("get", "/api/runs/private-run/tables/portfolio", None),
        ("get", "/api/runs/private-run/logs", None),
        ("get", "/api/runs/private-run/source", None),
        ("get", "/api/runs/private-run/attribution", None),
        ("get", "/api/runs/private-run/artifacts/report/download", None),
        ("get", "/api/runs/private-run/export/nav", None),
        ("get", "/api/runs/private-run/verdict", None),
        ("get", "/api/runs/private-run/overfit", None),
        ("get", "/api/runs/private-run/cost-sensitivity", None),
        ("get", "/api/runs/private-run/monthly-heatmap", None),
        ("post", "/api/runs/private-run/promote", {}),
        ("get", "/api/runs/private-run/coach_suggestion", None),
        ("delete", "/api/runs/private-run", None),
    ),
)
def test_global_run_routes_require_authentication(
    run_root: Path,
    client: TestClient,
    method: str,
    path: str,
    json_body: dict[str, object] | None,
) -> None:
    _write_run(run_root, "private-run", owner_user_id="owner")
    response = client.request(method, path, json=json_body)
    assert response.status_code == 401


def test_owner_filtering_nested_promote_owner_and_foreign_404(
    run_root: Path,
    client: TestClient,
) -> None:
    _write_run(run_root, "owned", owner_user_id="owner", market="owned-market")
    _write_run(
        run_root,
        "promoted",
        owner_user_id="owner",
        owner_username="alice",
        nested_owner=True,
        market="promoted-market",
    )
    _write_run(run_root, "foreign", owner_user_id="other", market="FOREIGN-SECRET-MARKET")
    _as_user("owner", "alice")

    listed = client.get("/api/runs")
    assert listed.status_code == 200
    assert {row["run_id"] for row in listed.json()} == {"owned", "promoted"}

    queried = client.post("/api/runs/query", json={})
    assert queried.status_code == 200
    assert {row["run_id"] for row in queried.json()["rows"]} == {"owned", "promoted"}
    assert "FOREIGN-SECRET-MARKET" not in queried.json()["available_filters"]["market"]

    assert client.get("/api/runs/promoted").status_code == 200
    assert client.get("/api/runs/foreign").status_code == 404
    assert client.get("/api/runs/compare", params={"run_ids": "foreign"}).status_code == 404

    download = client.get("/api/runs/owned/artifacts/report/download")
    assert download.status_code == 200
    assert download.content == b"PRIVATE:owned"


def test_canonical_promote_manifest_authorizes_stable_nested_owner(
    run_root: Path,
    client: TestClient,
) -> None:
    from app.ide.promote import promote_ide_run

    promoted = promote_ide_run(
        ide_run_id="ide-source-id",
        owner_username="alice",
        owner_user_id="owner",
        strategy_name="acl-producer-shape",
        strategy_code="quantbt.emit_result({})",
        result={
            "equity_curve": [
                {"t": "2026-07-11", "equity": 1.0, "net_return": 0.0},
                {"t": "2026-07-12", "equity": 1.01, "net_return": 0.01},
            ]
        },
        run_root=run_root,
    )
    _as_user("owner", "alice")

    response = client.get(f"/api/runs/{promoted.run_id}")
    assert response.status_code == 200
    assert response.json()["run_id"] == promoted.run_id


def test_delete_is_owner_only_and_public_demo_is_never_deletable(
    run_root: Path,
    client: TestClient,
) -> None:
    owned = _write_run(run_root, "owned", owner_user_id="owner")
    foreign = _write_run(run_root, "foreign", owner_user_id="other")
    public = run_root / "demo"
    shutil.copytree(
        main.PROJECT_ROOT / "data" / "artifacts" / "experiments" / "demo",
        public,
    )
    _as_user("owner")

    assert client.delete("/api/runs/foreign").status_code == 404
    assert foreign.is_dir()
    assert client.get("/api/runs/demo").status_code == 200
    assert client.delete("/api/runs/demo").status_code == 404
    assert public.is_dir()

    deleted = client.delete("/api/runs/owned")
    assert deleted.status_code == 200
    assert deleted.json() == {"deleted": "owned"}
    assert not owned.exists()


def test_delete_cas_does_not_remove_replacement_foreign_directory(
    run_root: Path,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_directory = _write_run(
        run_root,
        "race-delete",
        owner_user_id="owner",
    )
    backup = run_root / "race-delete-owner-backup"
    original_verify = main._verify_run_read_grant
    swapped = False

    def verify_then_swap(grant, user):  # noqa: ANN001, ANN202
        nonlocal swapped
        original_verify(grant, user)
        if not swapped:
            original_directory.rename(backup)
            _write_run(run_root, "race-delete", owner_user_id="other")
            swapped = True

    monkeypatch.setattr(main, "_verify_run_read_grant", verify_then_swap)
    _as_user("owner")

    response = client.delete("/api/runs/race-delete")
    assert response.status_code == 404
    assert backup.is_dir()
    assert (run_root / "race-delete").is_dir()
    replacement_manifest = json.loads(
        (run_root / "race-delete" / "run.json").read_text(encoding="utf-8")
    )
    assert replacement_manifest["owner_user_id"] == "other"


def test_delete_cas_rejects_exact_authorized_copy_with_extra_file(
    run_root: Path,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_directory = _write_run(
        run_root,
        "race-delete-copy",
        owner_user_id="owner",
    )
    backup = run_root / "race-delete-copy-owner-backup"
    original_verify = main._verify_run_read_grant
    swapped = False

    def verify_then_swap(grant, user):  # noqa: ANN001, ANN202
        nonlocal swapped
        original_verify(grant, user)
        if not swapped:
            original_directory.rename(backup)
            shutil.copytree(backup, run_root / "race-delete-copy")
            (run_root / "race-delete-copy" / "foreign-extra").write_text(
                "must-not-be-deleted",
                encoding="utf-8",
            )
            swapped = True

    monkeypatch.setattr(main, "_verify_run_read_grant", verify_then_swap)
    _as_user("owner")

    response = client.delete("/api/runs/race-delete-copy")
    assert response.status_code == 404
    assert backup.is_dir()
    assert (run_root / "race-delete-copy" / "foreign-extra").read_text(
        encoding="utf-8"
    ) == "must-not-be-deleted"


def test_allowlisted_name_with_noncanonical_manifest_is_not_public(
    run_root: Path,
    client: TestClient,
) -> None:
    fake_demo = _write_run(run_root, "demo")
    _as_user("reader")

    assert client.get("/api/runs/demo").status_code == 404
    assert client.delete("/api/runs/demo").status_code == 404
    assert fake_demo.is_dir()


def test_checked_in_demo_with_mutated_regular_artifact_is_not_public(
    run_root: Path,
    client: TestClient,
) -> None:
    public = run_root / "demo"
    shutil.copytree(
        main.PROJECT_ROOT / "data" / "artifacts" / "experiments" / "demo",
        public,
    )
    (public / "report.md").write_text(
        "MUTATED-PUBLIC-ARTIFACT-SENTINEL",
        encoding="utf-8",
    )
    _as_user("reader")

    response = client.get("/api/runs/demo/artifacts/report/download")
    assert response.status_code == 404
    assert b"MUTATED-PUBLIC-ARTIFACT-SENTINEL" not in response.content


def test_public_digest_pin_is_not_derived_from_same_mutable_runtime_path(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "same-path-project"
    runtime = project / "data" / "artifacts" / "experiments"
    runtime.mkdir(parents=True)
    public = runtime / "demo"
    shutil.copytree(
        main.PROJECT_ROOT / "data" / "artifacts" / "experiments" / "demo",
        public,
    )
    monkeypatch.setattr(run_detail_core, "RUN_ROOT", runtime)
    monkeypatch.setattr(main, "RUN_ROOT", runtime)
    monkeypatch.setattr(main, "PROJECT_ROOT", project)
    (public / "report.md").write_text("SAME-PATH-MUTATION-SENTINEL", encoding="utf-8")
    _as_user("reader")

    response = client.get("/api/runs/demo/artifacts/report/download")
    assert response.status_code == 404
    assert b"SAME-PATH-MUTATION-SENTINEL" not in response.content


def test_artifact_swap_after_path_validation_cannot_follow_symlink(
    run_root: Path,
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = _write_run(run_root, "swap-symlink", owner_user_id="owner")
    outside = tmp_path / "outside-secret.md"
    outside.write_text("ABA-OUTSIDE-SENTINEL", encoding="utf-8")
    original = main.artifact_download_path

    def validate_then_swap(run_id: str, artifact_name: str) -> Path:
        path = original(run_id, artifact_name)
        path.unlink()
        path.symlink_to(outside)
        return path

    monkeypatch.setattr(main, "artifact_download_path", validate_then_swap)
    _as_user("owner")

    response = client.get("/api/runs/swap-symlink/artifacts/report/download")
    assert response.status_code == 404
    assert b"ABA-OUTSIDE-SENTINEL" not in response.content
    assert directory.is_dir()


def test_regular_artifact_replacement_after_grant_fails_snapshot_hash(
    run_root: Path,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_run(run_root, "swap-regular", owner_user_id="owner")
    original = main.artifact_download_path

    def validate_then_replace(run_id: str, artifact_name: str) -> Path:
        path = original(run_id, artifact_name)
        path.write_text("FOREIGN-REGULAR-SENTINEL", encoding="utf-8")
        return path

    monkeypatch.setattr(main, "artifact_download_path", validate_then_replace)
    _as_user("owner")

    response = client.get("/api/runs/swap-regular/artifacts/report/download")
    assert response.status_code == 404
    assert b"FOREIGN-REGULAR-SENTINEL" not in response.content


def test_detail_artifact_stats_do_not_follow_midrequest_symlink(
    run_root: Path,
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = _write_run(run_root, "stats-race", owner_user_id="owner")
    outside = tmp_path / "outside-portfolio.csv"
    outside.write_text("timestamp,equity\na,1\nb,2\nc,3\n", encoding="utf-8")
    original = run_detail_core.build_artifact_stats

    def swap_during_stats(run_id: str):  # noqa: ANN202
        portfolio = directory / "portfolio.csv"
        original_payload = portfolio.read_bytes()
        portfolio.unlink()
        portfolio.symlink_to(outside)
        try:
            return original(run_id)
        finally:
            portfolio.unlink()
            portfolio.write_bytes(original_payload)

    monkeypatch.setattr(run_detail_core, "build_artifact_stats", swap_during_stats)
    _as_user("owner")

    response = client.get("/api/runs/stats-race")
    assert response.status_code == 200
    stats = response.json()["artifact_stats"]["portfolio"]
    assert stats["available"] is False
    assert stats["file_size_bytes"] is None
    assert stats["row_count"] is None


def test_query_uses_one_authorized_manifest_snapshot(
    run_root: Path,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = _write_run(
        run_root,
        "swap-run",
        owner_user_id="owner",
        market="OWNER-MARKET",
    )
    original = main._authorized_run_rows

    def snapshot_then_swap(user):  # noqa: ANN001, ANN202
        rows = original(user)
        manifest_path = directory / "run.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["owner_user_id"] = "other"
        manifest["market"] = "FOREIGN-SECRET-MARKET"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        return rows

    monkeypatch.setattr(main, "_authorized_run_rows", snapshot_then_swap)
    _as_user("owner")

    response = client.post("/api/runs/query", json={})
    assert response.status_code == 200
    assert response.json()["rows"][0]["market"] == "OWNER-MARKET"
    assert "FOREIGN-SECRET-MARKET" not in response.text


def test_non_regular_artifact_returns_404(
    run_root: Path,
    client: TestClient,
) -> None:
    directory = _write_run(run_root, "directory-artifact", owner_user_id="owner")
    (directory / "report.md").unlink()
    (directory / "report.md").mkdir()
    _as_user("owner")

    assert (
        client.get("/api/runs/directory-artifact/artifacts/report/download").status_code
        == 404
    )


def test_top_level_run_symlink_is_not_listed_or_readable(
    run_root: Path,
    client: TestClient,
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside-run"
    outside.mkdir()
    (outside / "run.json").write_text(
        json.dumps({"run_id": "top-link", "owner_user_id": "owner"}),
        encoding="utf-8",
    )
    (run_root / "top-link").symlink_to(outside, target_is_directory=True)
    _as_user("owner")

    assert client.get("/api/runs/top-link").status_code == 404
    assert all(row["run_id"] != "top-link" for row in client.get("/api/runs").json())


def test_manifest_and_artifact_symlinks_fail_closed(
    run_root: Path,
    client: TestClient,
    tmp_path: Path,
) -> None:
    outside_manifest = tmp_path / "outside-run.json"
    outside_manifest.write_text(
        json.dumps({"run_id": "manifest-link", "owner_user_id": "owner"}),
        encoding="utf-8",
    )
    manifest_link = run_root / "manifest-link"
    manifest_link.mkdir()
    (manifest_link / "run.json").symlink_to(outside_manifest)

    artifact_link = _write_run(run_root, "artifact-link", owner_user_id="owner")
    outside_report = tmp_path / "outside-report.md"
    outside_report.write_text("OUTSIDE-SENTINEL", encoding="utf-8")
    (artifact_link / "report.md").unlink()
    (artifact_link / "report.md").symlink_to(outside_report)
    _as_user("owner")

    assert client.get("/api/runs/manifest-link").status_code == 404
    detail = client.get("/api/runs/artifact-link")
    assert detail.status_code == 404
    download = client.get("/api/runs/artifact-link/artifacts/report/download")
    assert download.status_code == 404
    assert b"OUTSIDE-SENTINEL" not in download.content


def test_series_directory_symlink_fails_closed(
    run_root: Path,
    client: TestClient,
    tmp_path: Path,
) -> None:
    directory = _write_run(run_root, "series-link", owner_user_id="owner")
    outside_series = tmp_path / "outside-series"
    outside_series.mkdir()
    (outside_series / "equity.csv").write_text(
        "timestamp,value\n2026-07-12,999\n",
        encoding="utf-8",
    )
    (directory / "series").symlink_to(outside_series, target_is_directory=True)
    _as_user("owner")

    response = client.get("/api/runs/series-link/series", params={"series": "equity"})
    assert response.status_code == 404
    assert b"999" not in response.content


def test_final_series_file_symlink_fails_closed(
    run_root: Path,
    client: TestClient,
    tmp_path: Path,
) -> None:
    directory = _write_run(run_root, "series-file-link", owner_user_id="owner")
    (directory / "series").mkdir()
    outside = tmp_path / "equity.csv"
    outside.write_text("timestamp,value\n2026-07-12,999\n", encoding="utf-8")
    (directory / "series" / "equity.csv").symlink_to(outside)
    _as_user("owner")

    response = client.get(
        "/api/runs/series-file-link/series",
        params={"series": "equity"},
    )
    assert response.status_code == 404
    assert b"999" not in response.content


def test_conflicting_top_level_and_source_owner_claims_fail_closed(
    run_root: Path,
    client: TestClient,
) -> None:
    directory = _write_run(run_root, "conflict", owner_user_id="owner")
    manifest = json.loads((directory / "run.json").read_text(encoding="utf-8"))
    manifest["source"] = {"owner_user_id": "other"}
    (directory / "run.json").write_text(json.dumps(manifest), encoding="utf-8")
    _as_user("owner")

    assert client.get("/api/runs/conflict").status_code == 404


def test_promote_creator_must_match_authenticated_owner(
    run_root: Path,
    client: TestClient,
) -> None:
    _write_run(run_root, "creator-bound", owner_user_id="owner")
    _as_user("owner")

    response = client.post(
        "/api/runs/creator-bound/promote",
        json={"created_by": "other", "approver": "reviewer"},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "created_by must match authenticated user"


def test_promote_gate_identity_is_bound_to_authorized_bundle_digest(
    run_root: Path,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_run(run_root, "promote-bound", owner_user_id="owner")
    captured: dict = {}

    class _GateService:
        def open_gate(self, **values):  # noqa: ANN003, ANN201
            captured.update(values)
            return SimpleNamespace(
                decision="rejected",
                gate_id="gate-test",
                gap_list=["expected-test-gap"],
                verdict_text="blocked",
            )

    monkeypatch.setattr(main, "GATE_SERVICE", _GateService())
    _as_user("owner")

    response = client.post(
        "/api/runs/promote-bound/promote",
        json={"approver": "reviewer"},
    )
    assert response.status_code == 422
    bundle_digest = captured["evidence"]["run_bundle_sha256"]
    assert captured["model_id"] == f"run:promote-bound@sha256:{bundle_digest}"
    assert captured["evidence"]["run_manifest_sha256"]


def test_community_attachment_and_compliance_recheck_run_acl(
    run_root: Path,
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_run(run_root, "foreign-community", owner_user_id="other")
    database = tmp_path / "community.db"
    AuthService(database)
    community = CommunityService(database)
    monkeypatch.setattr(main, "COMMUNITY_SERVICE", community)
    monkeypatch.setattr(main, "COMPLIANCE_SERVICE", ComplianceService(database))
    _as_user("owner")

    create = client.post(
        "/api/community/posts",
        json={"content": "private attachment", "attached_run_id": "foreign-community"},
    )
    assert create.status_code == 404

    forged_post = community.create_post(
        "owner",
        "legacy foreign attachment",
        attached_run_id="foreign-community",
    )
    compliance = client.post(
        f"/api/community/posts/{forged_post.post_id}/check_compliance"
    )
    assert compliance.status_code == 404


def test_manifest_run_id_mismatch_is_not_authorized(
    run_root: Path,
    client: TestClient,
) -> None:
    directory = _write_run(run_root, "directory-id", owner_user_id="owner")
    manifest = json.loads((directory / "run.json").read_text(encoding="utf-8"))
    manifest["run_id"] = "different-id"
    (directory / "run.json").write_text(json.dumps(manifest), encoding="utf-8")
    _as_user("owner")

    assert client.get("/api/runs/directory-id").status_code == 404
    assert all(row["run_id"] != "directory-id" for row in client.get("/api/runs").json())

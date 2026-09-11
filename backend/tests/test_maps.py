from __future__ import annotations

from pathlib import Path
from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image

from pinky_control_center.adapters.mock import MockRobotAdapter
from pinky_control_center.main import create_app
from pinky_control_center.models import UserRole
from pinky_control_center.state_store import StateStore

ORIGIN = "http://localhost:5173"


def authenticated_client(tmp_path: Path):
    app = create_app(database_path=tmp_path / "control.db")
    client = TestClient(app)
    app.state.storage.create_or_reset_user("map-viewer", "map-viewer-password", UserRole.VIEWER)
    login = client.post("/api/v1/session", json={"username": "map-viewer", "password": "map-viewer-password"}, headers={"origin": ORIGIN})
    assert login.status_code == 200
    return client


def test_map_metadata_png_etag_and_authentication(tmp_path: Path) -> None:
    with authenticated_client(tmp_path) as client:
        listing = client.get("/api/v1/maps")
        assert listing.status_code == 200
        assert listing.json()["items"] == [
            {"map_id": "mock_lab", "name": "Mock Lab", "version": "1"},
            {"map_id": "mock_lab_b", "name": "Mock Lab B", "version": "1"},
        ]
        metadata = client.get("/api/v1/maps/mock_lab")
        assert metadata.status_code == 200
        assert metadata.json()["frame_id"] == "map"
        assert metadata.json()["origin"] == {"x": 0.0, "y": 0.0, "yaw": 0.0}
        png = client.get("/api/v1/maps/mock_lab/data", params={"version": "1"})
        assert png.status_code == 200
        assert png.headers["content-type"] == "image/png"
        assert png.content.startswith(b"\x89PNG")
        cells = Image.open(BytesIO(png.content)).convert("L")
        assert cells.size == (20, 20)
        assert cells.getpixel((5, 5)) == 254
        assert cells.getpixel((8, 5)) == 0
        assert cells.getpixel((15, 13)) == 205
        etag = png.headers["etag"]
        cached = client.get("/api/v1/maps/mock_lab/data", headers={"if-none-match": etag})
        assert cached.status_code == 304
        assert client.get("/api/v1/maps/missing").status_code == 404


def test_map_api_rejects_unauthenticated_requests(tmp_path: Path) -> None:
    app = create_app(database_path=tmp_path / "control.db")
    with TestClient(app) as client:
        assert client.get("/api/v1/maps").status_code == 401


def test_mock_map_pose_geometry_is_bounded_and_tf_invalid_clears_formation_measurements() -> None:
    source = MockRobotAdapter().snapshot()
    master = source.robots[0]
    assert source.map_id == "mock_lab"
    assert master.goal is not None and master.goal.frame_id == "map"
    assert 1 <= len(master.trail) <= 200
    assert 1 <= len(master.path) <= 200
    invalid = master.model_copy(update={"tf_valid": False, "tf_reason_code": "TF_UNAVAILABLE"})
    snapshot = source.model_copy(update={"robots": [invalid, source.robots[1]]})
    state = StateStore(lambda: snapshot).snapshot()
    assert state.formation.distance_m is None
    assert state.formation.gap_error_m is None
    assert state.formation.bearing_rad is None

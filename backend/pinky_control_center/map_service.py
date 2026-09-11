from __future__ import annotations

import io
from importlib import resources

from PIL import Image, ImageDraw
import yaml

from pinky_control_center.models import MapMetadata, MapOrigin, MapSummary


class MapService:
    """Provides deterministic mock map metadata and a cacheable occupancy PNG."""

    def __init__(self) -> None:
        configs = [yaml.safe_load(resource.read_text(encoding="utf-8")) for resource in sorted(resources.files("pinky_control_center").joinpath("resources", "maps").iterdir(), key=lambda resource: resource.name) if resource.name.endswith(".yaml")]
        self._metadata = {config["map_id"]: MapMetadata.model_validate({**config, "data_url": f"/api/v1/maps/{config['map_id']}/data"}) for config in configs}
        self.map_id = "mock_lab"
        self.version = self._metadata[self.map_id].version
        self._png = self._make_png()

    def summaries(self) -> list[MapSummary]:
        return [MapSummary(map_id=item.map_id, name=item.name, version=item.version) for item in self._metadata.values()]

    def metadata(self, map_id: str) -> MapMetadata | None:
        return self._metadata.get(map_id)

    def png(self, map_id: str, version: str | None = None) -> tuple[bytes, str] | None:
        metadata = self.metadata(map_id)
        if metadata is None or (version is not None and version != metadata.version):
            return None
        return self._png, f'"{metadata.map_id}:{metadata.version}"'

    @staticmethod
    def _make_png() -> bytes:
        # PNG rows are top-down while map coordinates are bottom-up from the
        # metadata origin. The dashboard converts world coordinates to this
        # same top-down row before looking up a pixel. One PNG pixel is one
        # occupancy cell: free 254, occupied 0, unknown 205.
        image = Image.new("L", (20, 20), 254)
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, 19, 19), outline=0, width=1)
        draw.rectangle((8, 4, 9, 13), fill=0)
        draw.rectangle((13, 12, 17, 17), fill=205)
        data = io.BytesIO()
        image.save(data, format="PNG")
        return data.getvalue()

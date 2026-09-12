from __future__ import annotations

import io
import math
from xml.etree import ElementTree
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
        self._png = {map_id: self._make_png(map_id, metadata) for map_id, metadata in self._metadata.items()}

    def summaries(self) -> list[MapSummary]:
        return [MapSummary(map_id=item.map_id, name=item.name, version=item.version) for item in self._metadata.values()]

    def metadata(self, map_id: str) -> MapMetadata | None:
        return self._metadata.get(map_id)

    def png(self, map_id: str, version: str | None = None) -> tuple[bytes, str] | None:
        metadata = self.metadata(map_id)
        if metadata is None or (version is not None and version != metadata.version):
            return None
        return self._png[map_id], f'"{metadata.map_id}:{metadata.version}"'

    @staticmethod
    def _make_png(map_id: str, metadata: MapMetadata) -> bytes:
        world = resources.files("pinky_control_center").joinpath("resources", "worlds", f"{map_id}.world")
        if world.is_file():
            return MapService._render_world(world, metadata)

        # PNG rows are top-down while map coordinates are bottom-up from the
        # metadata origin. The dashboard converts world coordinates to this
        # same top-down row before looking up a pixel. One PNG pixel is one
        # occupancy cell: free 254, occupied 0, unknown 205.
        image = Image.new("L", (20, 20), 254)
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, 19, 19), outline=0, width=1)
        if map_id == "mock_lab_b":
            draw.rectangle((3, 3, 6, 6), fill=0)
            draw.rectangle((12, 5, 16, 9), fill=205)
        else:
            draw.rectangle((8, 4, 9, 13), fill=0)
            draw.rectangle((13, 12, 17, 17), fill=205)
        data = io.BytesIO()
        image.save(data, format="PNG")
        return data.getvalue()

    @staticmethod
    def _render_world(world: object, metadata: MapMetadata) -> bytes:
        """Rasterize box collisions from a small SDF world into an occupancy map.

        The 260905 world intentionally defines its track walls as boxes.  Using
        collision geometry, rather than the Gazebo camera view, preserves the
        world/map coordinates and keeps the asset useful for Nav2 and the web
        dashboard alike.
        """
        root = ElementTree.fromstring(world.read_text(encoding="utf-8"))
        image = Image.new("L", (metadata.width, metadata.height), 254)
        draw = ImageDraw.Draw(image)
        map_origin = metadata.origin

        def pose(node: ElementTree.Element | None) -> tuple[float, float, float]:
            if node is None or node.text is None:
                return 0.0, 0.0, 0.0
            values = [float(value) for value in node.text.split()]
            return values[0], values[1], values[5] if len(values) >= 6 else 0.0

        def pixel(x: float, y: float) -> tuple[float, float]:
            return (
                (x - map_origin.x) / metadata.resolution,
                metadata.height - (y - map_origin.y) / metadata.resolution,
            )

        for model in root.findall("./world/model"):
            model_x, model_y, model_yaw = pose(model.find("./pose"))
            for link in model.findall("./link"):
                for collision in link.findall("./collision"):
                    size = collision.find("./geometry/box/size")
                    if size is None or size.text is None:
                        continue
                    sx, sy, _ = (float(value) for value in size.text.split())
                    local_x, local_y, local_yaw = pose(collision.find("./pose"))
                    angle = model_yaw + local_yaw
                    center_x = model_x + math.cos(model_yaw) * local_x - math.sin(model_yaw) * local_y
                    center_y = model_y + math.sin(model_yaw) * local_x + math.cos(model_yaw) * local_y
                    corners = []
                    for dx, dy in ((-sx / 2, -sy / 2), (sx / 2, -sy / 2), (sx / 2, sy / 2), (-sx / 2, sy / 2)):
                        x = center_x + math.cos(angle) * dx - math.sin(angle) * dy
                        y = center_y + math.sin(angle) * dx + math.cos(angle) * dy
                        corners.append(pixel(x, y))
                    draw.polygon(corners, fill=0)

        data = io.BytesIO()
        image.save(data, format="PNG")
        return data.getvalue()

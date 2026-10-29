"""Load static vessel profiles from package resources."""

from __future__ import annotations

import json
from pathlib import Path

from app.navigation.vessel.models import VesselProfile, VesselSource


class VesselNotFound(KeyError):
    pass


class VesselService:
    def __init__(self, resource_root: Path | None = None) -> None:
        root = resource_root or Path(__file__).resolve().parents[1] / "resources" / "vessels"
        self._profiles: dict[str, VesselProfile] = {}
        for path in sorted(root.glob("*.json")) if root.is_dir() else []:
            profile = _load_profile(path)
            self._profiles[profile.id] = profile

    def list(self) -> list[VesselProfile]:
        return [self._profiles[key] for key in sorted(self._profiles)]

    def get(self, vessel_id: str) -> VesselProfile:
        try:
            return self._profiles[vessel_id]
        except KeyError as error:
            raise VesselNotFound(vessel_id) from error


def _load_profile(path: Path) -> VesselProfile:
    payload = json.loads(path.read_text(encoding="utf-8"))
    identity = payload.get("identity", {})
    geometry = payload.get("geometry", {})
    mass = payload.get("mass", {})
    propulsion = payload.get("propulsion", {})
    speed = payload.get("speed", {})
    ice = payload.get("ice_capability", {})
    safety = payload.get("safety_constraints", {})
    return VesselProfile(
        id=str(identity["id"]),
        name=str(identity["name"]),
        vessel_type=str(identity.get("vessel_type", "")),
        operator=identity.get("operator"),
        length_m=float(geometry["length_m"]),
        beam_m=float(geometry["beam_m"]),
        design_draft_m=float(geometry.get("design_draft_m", safety.get("draft"))),
        design_displacement_t=mass.get("design_displacement_t"),
        propulsion_type=propulsion.get("type"),
        azipod_count=propulsion.get("azipod_count"),
        azipod_power_mw_each=propulsion.get("azipod_power_mw_each"),
        total_propulsion_power_mw=float(
            propulsion.get("total_propulsion_power_mw", safety.get("power"))
        ),
        service_speed_min_kn=float(speed["service_speed_min_kn"]),
        service_speed_max_kn=float(speed["service_speed_max_kn"]),
        maximum_speed_kn=float(speed["maximum_speed_kn"]),
        endurance_nmi=speed.get("endurance_nmi"),
        endurance_days=speed.get("endurance_days"),
        ice_class=ice.get("ice_class"),
        continuous_ice_thickness_m=float(ice["continuous_ice_thickness_m"]),
        continuous_snow_thickness_m=ice.get("continuous_snow_thickness_m"),
        continuous_ice_speed_min_kn=ice.get("continuous_ice_speed_min_kn"),
        continuous_ice_speed_max_kn=ice.get("continuous_ice_speed_max_kn"),
        safety_draft_m=float(safety.get("draft", geometry.get("design_draft_m"))),
        safety_power_mw=float(safety.get("power", propulsion.get("total_propulsion_power_mw"))),
        safety_speed_limit_kn=float(safety.get("speed_limit", speed["maximum_speed_kn"])),
        ukc_m=float(payload.get("ukc_m", 2.0)),
        sources=[
            VesselSource(
                title=str(source.get("title", "")),
                url=source.get("url"),
                fields=list(source.get("fields", [])),
            )
            for source in payload.get("sources", [])
        ],
    )

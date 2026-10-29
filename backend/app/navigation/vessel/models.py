"""Static vessel capability profile (no live position/sensor state)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class VesselSource(BaseModel):
    model_config = ConfigDict(frozen=True)

    title: str
    url: str | None = None
    fields: list[str] = Field(default_factory=list)


class VesselProfile(BaseModel):
    """Vessel data used by the planner; all values are static published data."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    vessel_type: str
    operator: str | None = None
    length_m: float = Field(gt=0)
    beam_m: float = Field(gt=0)
    design_draft_m: float = Field(gt=0)
    design_displacement_t: float | None = Field(default=None, gt=0)
    propulsion_type: str | None = None
    azipod_count: int | None = Field(default=None, ge=0)
    azipod_power_mw_each: float | None = Field(default=None, ge=0)
    total_propulsion_power_mw: float = Field(gt=0)
    service_speed_min_kn: float = Field(gt=0)
    service_speed_max_kn: float = Field(gt=0)
    maximum_speed_kn: float = Field(gt=0)
    endurance_nmi: float | None = Field(default=None, gt=0)
    endurance_days: float | None = Field(default=None, gt=0)
    ice_class: str | None = None
    continuous_ice_thickness_m: float = Field(gt=0)
    continuous_snow_thickness_m: float | None = Field(default=None, ge=0)
    continuous_ice_speed_min_kn: float | None = Field(default=None, ge=0)
    continuous_ice_speed_max_kn: float | None = Field(default=None, ge=0)
    safety_draft_m: float = Field(gt=0)
    safety_power_mw: float = Field(gt=0)
    safety_speed_limit_kn: float = Field(gt=0)
    ukc_m: float = Field(default=2.0, ge=0)
    sources: list[VesselSource] = Field(default_factory=list)

    @property
    def required_depth_m(self) -> float:
        return self.safety_draft_m + self.ukc_m

    @property
    def reference_speed_kn(self) -> float:
        """Open-water power-curve reference speed (V3 uses 12 kn)."""
        return 12.0

    @property
    def search_min_speed_kn(self) -> float:
        return 0.5

    @property
    def operation_min_speed_kn(self) -> float:
        return 1.0

    @property
    def power_limit_mw(self) -> float:
        return self.safety_power_mw

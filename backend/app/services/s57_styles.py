from dataclasses import dataclass


def _format_scale_denominator(value: float) -> str:
    """Canonical float formatting for SLD scale denominators (e.g. ``25000.0``).

    Normalizes through ``float`` so int and float inputs hash identically.
    """
    return str(float(value))


@dataclass(frozen=True)
class S57StylePreset:
    code: str
    name: str
    geometry: str
    color: str
    fill_color: str | None = None

    def render_sld(
        self,
        min_scale_denominator: float | None = None,
        max_scale_denominator: float | None = None,
    ) -> str:
        if self.geometry == "point":
            symbolizer = f"""
              <sld:PointSymbolizer><sld:Graphic><sld:Mark>
                <sld:WellKnownName>circle</sld:WellKnownName>
                <sld:Fill><sld:CssParameter name="fill">{self.color}</sld:CssParameter></sld:Fill>
                <sld:Stroke><sld:CssParameter name="stroke">#102c3a</sld:CssParameter><sld:CssParameter name="stroke-width">1</sld:CssParameter></sld:Stroke>
              </sld:Mark><sld:Size>7</sld:Size></sld:Graphic></sld:PointSymbolizer>"""
        elif self.geometry == "polygon":
            symbolizer = f"""
              <sld:PolygonSymbolizer>
                <sld:Fill><sld:CssParameter name="fill">{self.fill_color or self.color}</sld:CssParameter><sld:CssParameter name="fill-opacity">0.42</sld:CssParameter></sld:Fill>
                <sld:Stroke><sld:CssParameter name="stroke">{self.color}</sld:CssParameter><sld:CssParameter name="stroke-width">1.2</sld:CssParameter></sld:Stroke>
              </sld:PolygonSymbolizer>"""
        else:
            symbolizer = f"""
              <sld:LineSymbolizer><sld:Stroke>
                <sld:CssParameter name="stroke">{self.color}</sld:CssParameter>
                <sld:CssParameter name="stroke-width">1.5</sld:CssParameter>
              </sld:Stroke></sld:LineSymbolizer>"""
        # Scale-dependent rendering: omit both elements when no scale is set so
        # the default output stays byte-identical with the pre-scale-rules SLD.
        scale_blocks = []
        if min_scale_denominator is not None:
            scale_blocks.append(
                "<sld:MinScaleDenominator>"
                f"{_format_scale_denominator(min_scale_denominator)}"
                "</sld:MinScaleDenominator>"
            )
        if max_scale_denominator is not None:
            scale_blocks.append(
                "<sld:MaxScaleDenominator>"
                f"{_format_scale_denominator(max_scale_denominator)}"
                "</sld:MaxScaleDenominator>"
            )
        scale_xml = f"\n      {'\n      '.join(scale_blocks)}" if scale_blocks else ""
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<sld:StyledLayerDescriptor version="1.0.0"
  xmlns:sld="http://www.opengis.net/sld"
  xmlns:ogc="http://www.opengis.net/ogc"
  xmlns:xlink="http://www.w3.org/1999/xlink"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <sld:NamedLayer><sld:Name>{self.code}</sld:Name><sld:UserStyle>
    <sld:Title>{self.name}</sld:Title><sld:FeatureTypeStyle><sld:Rule>{scale_xml}
      {symbolizer}
    </sld:Rule></sld:FeatureTypeStyle>
  </sld:UserStyle></sld:NamedLayer>
</sld:StyledLayerDescriptor>"""


PRESETS = {
    "coastline": S57StylePreset("s57_coastline", "S-57 岸线", "line", "#2f4858"),
    "land": S57StylePreset("s57_land", "S-57 陆地", "polygon", "#7b725f", "#d9c9a5"),
    "depth": S57StylePreset("s57_depth", "S-57 水深区域", "polygon", "#5b9db7", "#b9e2ee"),
    "contour": S57StylePreset("s57_contour", "S-57 等深线", "line", "#4f8ca8"),
    "sounding": S57StylePreset("s57_sounding", "S-57 水深点", "point", "#245267"),
    "navigation": S57StylePreset("s57_navigation", "S-57 航道", "line", "#b14e9a"),
    "aid": S57StylePreset("s57_aid", "S-57 助航标志", "point", "#f3b33d"),
    "danger": S57StylePreset("s57_danger", "S-57 危险物", "point", "#d94b4b"),
    "restricted": S57StylePreset("s57_restricted", "S-57 限制区", "polygon", "#c0507a", "#efb4c9"),
    "anchorage": S57StylePreset("s57_anchorage", "S-57 锚地", "polygon", "#516fb6", "#b9c8ed"),
}

OBJECT_CLASS_TO_PRESET = {
    "COALNE": "coastline",
    "LNDARE": "land",
    "DEPARE": "depth",
    "DEPCNT": "contour",
    "SOUNDG": "sounding",
    "DRGARE": "navigation",
    "NAVLNE": "navigation",
    "FAIRWY": "navigation",
    "LIGHTS": "aid",
    "BOYSPP": "aid",
    "BOYLAT": "aid",
    "BOYCAR": "aid",
    "BOYSAW": "aid",
    "BCNSPP": "aid",
    "BCNLAT": "aid",
    "BCNCAR": "aid",
    "BCNSAW": "aid",
    "WRECKS": "danger",
    "OBSTRN": "danger",
    "UWTROC": "danger",
    "RESARE": "restricted",
    "ACHARE": "anchorage",
}


def preset_for_object_class(object_class: str) -> S57StylePreset | None:
    key = OBJECT_CLASS_TO_PRESET.get(object_class.upper())
    return PRESETS.get(key) if key else None

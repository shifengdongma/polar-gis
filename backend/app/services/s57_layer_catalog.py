from dataclasses import dataclass
from types import MappingProxyType
from typing import Final


@dataclass(frozen=True, slots=False)
class S57LayerRule:
    code: str
    object_name_zh: str
    display_category: str
    load_profile: str
    display_priority: int
    recommended: bool
    renderable: bool
    default_visible: bool
    # Phase 4: scale-dependent rendering hints
    min_scale_denominator: float | None = None
    max_scale_denominator: float | None = None
    low_zoom_visible: bool = True
    render_cost: int = 1

    @property
    def sort_key(self) -> tuple[int, str]:
        return (self.display_priority, self.code)


_CORE_CHART_RULES = MappingProxyType(
    {
        "DEPARE": ("bathymetry", 10),
        "SEAARE": ("bathymetry", 10),
        "COALNE": ("land_coast", 20),
        "LNDARE": ("land_coast", 20),
        "ICEARE": ("land_coast", 20),
        "DEPCNT": ("depth", 20),
        "SOUNDG": ("depth", 30),
        "OBSTRN": ("hazard", 40),
        "WRECKS": ("hazard", 40),
        "UWTROC": ("hazard", 40),
        "CTNARE": ("hazard", 40),
        "UNSARE": ("hazard", 40),
    }
)
CORE_CHART: Final = frozenset(_CORE_CHART_RULES)
NAVIGATION_RECOMMENDED: Final = frozenset(
    {
        "LIGHTS",
        "FOGSIG",
        "BOYCAR",
        "BOYINB",
        "BOYISD",
        "BOYSAW",
        "BOYSPP",
        "BCNISD",
        "BCNSPP",
        "TOPMAR",
        "RTPBCN",
        "RDOSTA",
        "RDOCAL",
        "RETRFL",
        "RCRTCL",
        "RCTLPT",
        "TSSBND",
        "TSSLPT",
        "TSEZNE",
        "TSSRON",
        "RESARE",
        "DMPGRD",
        "HRBARE",
        "SLCONS",
    }
)
OPTIONAL_THEMATIC: Final = frozenset(
    {
        "ADMARE",
        "BUAARE",
        "BUISGL",
        "CANALS",
        "CBLSUB",
        "CONZNE",
        "COSARE",
        "CURENT",
        "EXEZNE",
        "FNCLNE",
        "FSHZNE",
        "LAKARE",
        "LNDELV",
        "LNDMRK",
        "LNDRGN",
        "LOCMAG",
        "MAGVAR",
        "MARCUL",
        "OFSPLF",
        "OSPARE",
        "PILPNT",
        "PIPSOL",
        "RIVERS",
        "SBDARE",
        "STSLNE",
        "TESARE",
    }
)
METADATA_QUALITY: Final = frozenset({"M_COVR", "M_CSCL", "M_NPUB", "M_NSYS", "M_QUAL"})
NON_SPATIAL: Final = frozenset({"DSID", "C_AGGR"})

_OBJECT_NAMES = MappingProxyType(
    {
        "LNDARE": "陆地区域",
        "DEPARE": "水深区域",
        "DEPCNT": "等深线",
        "SOUNDG": "水深点",
        "SEAARE": "海域",
        "ICEARE": "冰区",
        "OBSTRN": "障碍物",
        "WRECKS": "沉船",
        "UWTROC": "水下或露出水面的礁石",
        "CTNARE": "航道管制区域",
        "UNSARE": "未经测量区域",
        "LIGHTS": "灯标",
        "FOGSIG": "雾号",
        "BOYCAR": "方位浮标",
        "BOYINB": "设施浮标",
        "BOYISD": "孤立危险物浮标",
        "BOYSAW": "安全水域浮标",
        "BOYSPP": "专用浮标",
        "BCNISD": "孤立危险物标",
        "BCNSPP": "专用标",
        "TOPMAR": "顶标",
        "RTPBCN": "雷达应答标",
        "RDOSTA": "无线电台",
        "RDOCAL": "无线电呼叫点",
        "RETRFL": "雷达反射器",
        "RCRTCL": "雷达测距线",
        "RCTLPT": "雷达控制点",
        "TSSBND": "交通分隔带边界",
        "TSSLPT": "交通分隔线",
        "TSEZNE": "交通分隔区域",
        "TSSRON": "环形交通分隔制",
        "RESARE": "限制区域",
        "DMPGRD": "倾倒区",
        "HRBARE": "港区",
        "SLCONS": "岸线构筑物",
        "ADMARE": "行政区域",
        "BUAARE": "建筑区域",
        "BUISGL": "单体建筑",
        "CANALS": "运河",
        "CBLSUB": "海底电缆",
        "CONZNE": "毗连区",
        "COSARE": "大陆架区域",
        "CURENT": "水流",
        "EXEZNE": "专属经济区",
        "FNCLNE": "栅栏线",
        "FSHZNE": "渔区",
        "LAKARE": "湖泊",
        "LNDELV": "陆地高程",
        "LNDMRK": "陆标",
        "LNDRGN": "陆地区域名",
        "LOCMAG": "局部磁异常",
        "MAGVAR": "磁差",
        "MARCUL": "海事文化设施",
        "OFSPLF": "海上平台",
        "OSPARE": "近海生产区",
        "PILPNT": "引航站",
        "PIPSOL": "海底管线",
        "RIVERS": "河流",
        "SBDARE": "海床区域",
        "STSLNE": "直线领海基线",
        "TESARE": "领海区域",
        "M_COVR": "海图覆盖范围",
        "M_CSCL": "编绘比例尺",
        "M_NPUB": "航海用途",
        "M_NSYS": "助航标志系统",
        "M_QUAL": "数据质量",
        "DSID": "数据集标识",
        "C_AGGR": "要素集合",
    }
)

_NAVIGATION_AIDS: Final = frozenset(
    {
        "LIGHTS",
        "FOGSIG",
        "BOYCAR",
        "BOYINB",
        "BOYISD",
        "BOYSAW",
        "BOYSPP",
        "BCNISD",
        "BCNSPP",
        "TOPMAR",
        "RTPBCN",
        "RDOSTA",
        "RDOCAL",
        "RETRFL",
        "RCRTCL",
        "RCTLPT",
    }
)
_ROUTING: Final = frozenset({"TSSBND", "TSSLPT", "TSEZNE", "TSSRON"})

# Phase 4: Per-object-class scale-dependent rendering hints.
# These are the single source of truth shared between frontend scheduler and backend SLD.
_SCALE_RULES: Final[dict[str, dict[str, float | None | bool | int]]] = {
    # Always-visible reference layers
    "COALNE": {"min_scale_denom": None, "low_zoom_visible": True, "render_cost": 1},
    "LNDARE": {"min_scale_denom": None, "low_zoom_visible": True, "render_cost": 1},
    "DEPARE": {"min_scale_denom": None, "low_zoom_visible": True, "render_cost": 1},
    "SEAARE": {"min_scale_denom": None, "low_zoom_visible": True, "render_cost": 1},
    "ICEARE": {"min_scale_denom": None, "low_zoom_visible": True, "render_cost": 1},
    # Contours — hide fine lines at small scales
    "DEPCNT": {"min_scale_denom": 500_000.0, "low_zoom_visible": False, "render_cost": 2},
    # High-density point layers — only at large scales
    "SOUNDG": {"min_scale_denom": 25_000.0, "low_zoom_visible": False, "render_cost": 4},
    # Navigation aids — medium+ scales
    "LIGHTS": {"min_scale_denom": 50_000.0, "low_zoom_visible": False, "render_cost": 3},
    "FOGSIG": {"min_scale_denom": 50_000.0, "low_zoom_visible": False, "render_cost": 3},
    "BOYCAR": {"min_scale_denom": 50_000.0, "low_zoom_visible": False, "render_cost": 3},
    "BOYINB": {"min_scale_denom": 50_000.0, "low_zoom_visible": False, "render_cost": 3},
    "BOYISD": {"min_scale_denom": 50_000.0, "low_zoom_visible": False, "render_cost": 3},
    "BOYLAT": {"min_scale_denom": 50_000.0, "low_zoom_visible": False, "render_cost": 3},
    "BOYSAW": {"min_scale_denom": 50_000.0, "low_zoom_visible": False, "render_cost": 3},
    "BOYSPP": {"min_scale_denom": 50_000.0, "low_zoom_visible": False, "render_cost": 3},
    "BCNCAR": {"min_scale_denom": 50_000.0, "low_zoom_visible": False, "render_cost": 3},
    "BCNISD": {"min_scale_denom": 50_000.0, "low_zoom_visible": False, "render_cost": 3},
    "BCNLAT": {"min_scale_denom": 50_000.0, "low_zoom_visible": False, "render_cost": 3},
    "BCNSAW": {"min_scale_denom": 50_000.0, "low_zoom_visible": False, "render_cost": 3},
    "BCNSPP": {"min_scale_denom": 50_000.0, "low_zoom_visible": False, "render_cost": 3},
    "TOPMAR": {"min_scale_denom": 50_000.0, "low_zoom_visible": False, "render_cost": 3},
    # Danger objects — medium+ scales
    "WRECKS": {"min_scale_denom": 100_000.0, "low_zoom_visible": False, "render_cost": 2},
    "OBSTRN": {"min_scale_denom": 100_000.0, "low_zoom_visible": False, "render_cost": 2},
    "UWTROC": {"min_scale_denom": 100_000.0, "low_zoom_visible": False, "render_cost": 2},
    # Mid-zoom layers
    "UNSARE": {"min_scale_denom": 200_000.0, "low_zoom_visible": False, "render_cost": 2},
    "CTNARE": {"min_scale_denom": 200_000.0, "low_zoom_visible": False, "render_cost": 2},
    "RESARE": {"min_scale_denom": 200_000.0, "low_zoom_visible": False, "render_cost": 2},
    "HRBARE": {"min_scale_denom": 200_000.0, "low_zoom_visible": False, "render_cost": 2},
    "SLCONS": {"min_scale_denom": 200_000.0, "low_zoom_visible": False, "render_cost": 2},
}

_INVALID_GEOMETRY_TYPES: Final = frozenset(
    {"", "unknown", "none", "null", "n/a", "no geometry", "geometryless", "无", "无几何"}
)


def has_valid_geometry(geometry_type: str | None) -> bool:
    if geometry_type is None:
        return False
    return geometry_type.strip().casefold() not in _INVALID_GEOMETRY_TYPES


def classify_s57_layer(
    code: str, geometry_type: str | None, style_mapped: bool
) -> S57LayerRule:
    normalized_code = code.rsplit(":", maxsplit=1)[-1].strip().upper()
    geometry_valid = has_valid_geometry(geometry_type)

    if normalized_code in CORE_CHART:
        load_profile = "core_chart"
        display_category, display_priority = _CORE_CHART_RULES[normalized_code]
    elif normalized_code in NAVIGATION_RECOMMENDED:
        load_profile = "navigation_recommended"
        if normalized_code in _NAVIGATION_AIDS:
            display_category, display_priority = "navigation_aid", 50
        elif normalized_code in _ROUTING:
            display_category, display_priority = "routing", 60
        else:
            display_category, display_priority = "restriction_harbor", 70
    elif normalized_code in OPTIONAL_THEMATIC:
        load_profile = "optional_thematic"
        display_category, display_priority = "optional_thematic", 100
    elif normalized_code in METADATA_QUALITY:
        load_profile = "metadata_quality"
        display_category, display_priority = "metadata_quality", 200
    elif normalized_code in NON_SPATIAL or not geometry_valid:
        load_profile = "non_spatial"
        display_category, display_priority = "non_spatial", 900
    elif normalized_code.startswith("M_"):
        load_profile = "metadata_quality"
        display_category, display_priority = "metadata_quality", 200
    else:
        load_profile = "optional_other"
        display_category, display_priority = "optional_other", 100

    renderable = geometry_valid and normalized_code not in NON_SPATIAL
    recommended = load_profile in {"core_chart", "navigation_recommended"} and bool(style_mapped)
    object_name_zh = _OBJECT_NAMES.get(normalized_code, normalized_code or "未命名对象")

    # Phase 4: apply scale-dependent rendering hints
    scale_hints = _SCALE_RULES.get(normalized_code, {})
    min_scale = scale_hints.get("min_scale_denom", None)
    low_zoom = scale_hints.get("low_zoom_visible", True)
    rcost = scale_hints.get("render_cost", 1)

    return S57LayerRule(
        code=normalized_code,
        object_name_zh=object_name_zh,
        display_category=display_category,
        load_profile=load_profile,
        display_priority=display_priority,
        recommended=recommended,
        renderable=renderable,
        default_visible=False,
        min_scale_denominator=min_scale,
        max_scale_denominator=None,
        low_zoom_visible=low_zoom,
        render_cost=rcost,
    )

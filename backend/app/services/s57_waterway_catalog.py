"""S-57 航道专题 taxonomy.

This module is deliberately independent from :mod:`app.services.s57_layer_catalog`.
The legacy catalog controls chart loading profiles, render bundles and GWC
transport; changing its exact sets would alter bulk-load semantics. The
waterway thematic only exposes a read-only taxonomy over already imported
S-57 layers.

Classification is based on the S-57 object classes named in the task:
fairways/recommended routes, traffic-separation measures, controlled areas and
waterway environment objects. Auxiliary classes are related but must not be
labelled as fairways.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final


@dataclass(frozen=True, slots=True)
class WaterwayClassRule:
    code: str
    name_zh: str
    group: str
    group_name_zh: str
    auxiliary: bool
    default_selected: bool
    description: str


WATERWAY_GROUP_ORDER: Final[tuple[str, ...]] = (
    "fairway_route",
    "traffic_separation",
    "restriction",
    "waterway_environment",
)

_GROUP_NAMES: Final = MappingProxyType(
    {
        "fairway_route": "航道与推荐路线",
        "traffic_separation": "交通分隔制",
        "restriction": "航行限制与管制",
        "waterway_environment": "航道环境辅助要素",
    }
)

# Primary thematic objects: these are the classes users explicitly search as
# "航道专题". TSS* are traffic-separation measures, not auxiliary objects.
_PRIMARY: Final[tuple[tuple[str, str, str, bool, str], ...]] = (
    ("FAIRWY", "航道", "fairway_route", True, "S-57 航道对象"),
    ("RECTRC", "推荐航路", "fairway_route", True, "S-57 推荐航路对象"),
    ("NAVLNE", "航行线", "fairway_route", True, "S-57 航行线对象"),
    ("TWRTPT", "双向航路段", "fairway_route", True, "S-57 双向航路段对象"),
    ("DWRTCL", "深水航道中心线", "fairway_route", True, "S-57 深水航道中心线；DRVAL1 是最小指示深度，不是保证安全水深"),
    ("DWRTPT", "深水航道部分", "fairway_route", True, "S-57 深水航道部分（面/点）；DRVAL1 是最小指示深度，不是保证安全水深"),
    ("RCRTCL", "推荐航线中心线", "fairway_route", True, "S-57 推荐航线中心线；不是整条东北航道"),
    ("RCTLPT", "推荐通航车道部分", "fairway_route", False, "S-57 推荐通航车道部分（面/点）；不是连续中心线，也不属于 TSS 交通分隔制"),
    ("CANALS", "运河", "fairway_route", True, "S-57 运河对象"),
    ("TSSLPT", "分道通航制车道部分", "traffic_separation", True, "S-57 分道通航制车道部分对象（面状分区）"),
    ("TSSBND", "交通分隔带边界", "traffic_separation", True, "S-57 交通分隔带边界对象"),
    ("TSEZNE", "交通分隔区域", "traffic_separation", True, "S-57 交通分隔区域对象"),
    ("TSSRON", "环形交通分隔制", "traffic_separation", True, "S-57 环形交通分隔制对象"),
    ("CTNARE", "航道管制区域", "restriction", False, "S-57 谨慎航行/管制相关区域"),
    ("DRGARE", "疏浚区域", "waterway_environment", False, "S-57 疏浚区域对象"),
)

# Related objects that help interpret a waterway but are not fairways.
_AUXILIARY: Final[tuple[tuple[str, str, str, bool, str], ...]] = (
    ("RESARE", "限制区域", "restriction", False, "S-57 限制区域（辅助）"),
    ("ACHARE", "锚地", "waterway_environment", False, "S-57 锚地（辅助）"),
    ("BERTHS", "泊位", "waterway_environment", False, "S-57 泊位（辅助）"),
    ("PILPNT", "引航站", "waterway_environment", False, "S-57 引航站（辅助）"),
    ("DEPARE", "水深区域", "waterway_environment", False, "S-57 水深区域（辅助）"),
    ("DEPCNT", "等深线", "waterway_environment", False, "S-57 等深线（辅助）"),
    ("SOUNDG", "水深点", "waterway_environment", False, "S-57 水深点（辅助）"),
)


def _build(
    definitions: tuple[tuple[str, str, str, bool, str], ...],
    *,
    auxiliary: bool,
) -> MappingProxyType[str, WaterwayClassRule]:
    rules: dict[str, WaterwayClassRule] = {}
    for code, name, group, default_selected, description in definitions:
        rules[code] = WaterwayClassRule(
            code=code,
            name_zh=name,
            group=group,
            group_name_zh=_GROUP_NAMES[group],
            auxiliary=auxiliary,
            default_selected=default_selected,
            description=description,
        )
    return MappingProxyType(rules)


_WATERWAY_RULES: Final = _build(_PRIMARY, auxiliary=False)
_AUXILIARY_RULES: Final = _build(_AUXILIARY, auxiliary=True)

S57_WATERWAY_OBJECT_CLASSES: Final[frozenset[str]] = frozenset(_WATERWAY_RULES)
S57_WATERWAY_AUXILIARY_CLASSES: Final[frozenset[str]] = frozenset(_AUXILIARY_RULES)
S57_WATERWAY_ALL_CLASSES: Final[frozenset[str]] = (
    S57_WATERWAY_OBJECT_CLASSES | S57_WATERWAY_AUXILIARY_CLASSES
)

WATERWAY_CLASS_RULES: Final = MappingProxyType(
    {**_WATERWAY_RULES, **_AUXILIARY_RULES}
)

# Common S-57 attribute labels. Value enumerations (CAT*, STATUS, RESTRN...) are
# intentionally shown as raw codes: the repository has no authoritative local
# S-57 value catalogue, so inventing translations would be unsafe.
FIELD_LABELS: Final = MappingProxyType(
    {
        "rcid": "S-57 记录标识",
        "objnam": "英文名称",
        "nobjnm": "国家语言名称",
        "inform": "英文补充信息",
        "ninfom": "国家语言补充信息",
        "status": "状态（原始代码）",
        "restrn": "限制（原始代码）",
        "condtn": "状况（原始代码）",
        "datsta": "起始日期",
        "datend": "结束日期",
        "scamin": "最小显示比例尺",
        "quasou": "数据质量（原始代码）",
        "drval1": "深度下限（按对象语义解释）",
        "drval2": "深度上限（按对象语义解释）",
        "valdco": "等深线数值（原始值）",
        "valsou": "最小深度/测深值（按对象语义解释）",
        "watlev": "水位/潮汐影响（原始代码）",
        "expsou": "相对于海床的位置（原始代码）",
        "tecsou": "水深测量技术（原始代码）",
        "verdat": "垂直基准（原始代码）",
        "sordat": "数据日期",
        "sorind": "数据来源",
        "prim": "几何图元类型",
        "grup": "分组标识",
        "objl": "对象类代码",
        "rver": "记录版本",
        "agen": "生产机构代码",
        "fidn": "要素标识号",
        "fids": "要素标识细分",
        "lnam": "长名称标识",
    }
)

FIELD_DESCRIPTIONS: Final = MappingProxyType(
    {
        "objnam": "S-57 OBJNAM 原始英文名称；缺失时不生成名称。",
        "nobjnm": "S-57 NOBJNM 国家语言名称；仅在 OBJNAM 缺失时作为显示名称。",
        "inform": "S-57 INFORM 英文补充说明。",
        "ninfom": "S-57 NINFOM 国家语言补充说明。",
        "drval1": "S-57 DRVAL1 深度范围下限；不同对象类别含义不同，不是航道保证水深。",
        "drval2": "S-57 DRVAL2 深度范围上限；不同对象类别含义不同，不是航道保证水深。",
        "valdco": "S-57 VALDCO 等深线数值；不是保证可通行深度。",
        "valsou": "S-57 VALSOU 最小深度/测深值；含义随对象类别定义，不是航道保证水深。",
        "watlev": "S-57 WATLEV 水位/潮汐影响代码；当前保留原始代码。",
        "expsou": "S-57 EXPSOU 相对于海床的位置代码；当前保留原始代码。",
        "tecsou": "S-57 TECSOU 水深测量技术代码；当前保留原始代码。",
        "verdat": "S-57 VERDAT 垂直基准代码；当前保留原始代码，缺失时表示未知。",
        "lnam": "S-57 LNAM 长名称标识；用于追溯原始对象。",
        "status": "S-57 状态代码；当前保留原始代码，未做无依据的中文枚举翻译。",
        "restrn": "S-57 限制代码；当前保留原始代码。",
        "condtn": "S-57 状况代码；当前保留原始代码。",
    }
)

CURATED_FIELD_ORDER: Final[tuple[str, ...]] = (
    "objnam",
    "nobjnm",
    "inform",
    "ninfom",
    "status",
    "restrn",
    "condtn",
    "datsta",
    "datend",
    "scamin",
    "quasou",
    "drval1",
    "drval2",
    "valdco",
    "valsou",
    "watlev",
    "expsou",
    "tecsou",
    "verdat",
    "lnam",
    "rcid",
)


def normalize_object_class(code: str | None) -> str:
    if not code:
        return ""
    normalized = str(code).rsplit(":", maxsplit=1)[-1].strip().upper()
    return normalized


def classify_waterway(code: str | None) -> WaterwayClassRule | None:
    return WATERWAY_CLASS_RULES.get(normalize_object_class(code))


def is_waterway_class(code: str | None) -> bool:
    return normalize_object_class(code) in S57_WATERWAY_ALL_CLASSES


def field_label(field: str, object_class: str | None = None) -> str:
    normalized = field.lower()
    if normalized in FIELD_LABELS:
        return FIELD_LABELS[normalized]
    if normalized.startswith("cat"):
        # CAT* meaning is object-class specific; never translate by prefix.
        return f"S-57 类别属性（{normalized.upper()}）"
    return normalized.upper()

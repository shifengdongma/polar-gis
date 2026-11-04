import type { MapLayerConfig } from '../types'

export const s57ObjectNames: Record<string, string> = {
  C_ASSO: '要素关联',
  C_AGGR: '要素集合',
  M_COVR: '海图覆盖范围',
  M_CSCL: '编绘比例尺',
  M_NSYS: '助航标志系统',
  M_NPUB: '航海用途',
  M_QUAL: '数据质量',
  WRECKS: '沉船',
  WATTUR: '水流湍流',
  UWTROC: '水下或露出水面的礁石',
  TOPMAR: '顶标',
  TESARE: '领海区域',
  STSLNE: '直线领海基线',
  SOUNDG: '水深点',
  SLOTOP: '斜坡顶部',
  SBDARE: '海床区域',
  SEAARE: '海域',
  ROADWY: '道路',
  RIVERS: '河流',
  RESARE: '限制区域',
  RECTRC: '推荐航路',
  RDOSTA: '无线电台',
  COALNE: '海岸线',
  DEPARE: '水深区域',
  DEPCNT: '等深线',
  LIGHTS: '灯标',
  LNDMRK: '陆标',
  BCNLAT: '侧标',
  BCNCAR: '方位标',
  BCNISD: '孤立危险物标',
  BCNSAW: '安全水域标',
  BCNSPP: '专用标',
  BOYLAT: '侧面浮标',
  BOYCAR: '方位浮标',
  BOYISD: '孤立危险物浮标',
  BOYSAW: '安全水域浮标',
  BOYSPP: '专用浮标',
  OBSTRN: '障碍物',
  NAVLNE: '航行线',
  TWRTPT: '双向航路段',
  TSSLPT: '交通分隔线',
  TSSBND: '交通分隔带边界',
  TSEZNE: '交通分隔区域',
  TSSRON: '环形交通分隔制',
  FAIRWY: '航道',
  CANALS: '运河',
  FSHFAC: '渔业设施',
  FSHRES: '渔业限制区',
  HARBR: '港口',
  HRBFAC: '港口设施',
  ACHARE: '锚地',
  BERTHS: '泊位',
  PILPNT: '引航站',
  MARCUL: '海事文化设施',
  PIPARE: '管线区域',
  CBLSUB: '海底电缆',
  CTNARE: '航道管制区域',
  DRGARE: '疏浚区域',
  DYKCON: '堤坝',
  SLCONS: '岸线构筑物',
  LAKARE: '湖泊',
  MAGVAR: '磁差',
  PRCARE: '预防区域',
  RAILWY: '铁路',
  RUNWAY: '跑道',
  BUARE: '建筑区域',
  BUAARE: '建筑区域',
}

/**
 * Short, honest descriptions for common S-57 chart object classes.
 * These describe the object definition, not live navigation status or a
 * surveyed/guaranteed safe channel. Unknown codes are intentionally absent.
 */
export const s57ObjectDescriptions: Record<string, string> = {
  COALNE: '海岸线对象，表示陆地与水域的分界线。',
  LNDARE: '陆地区域对象，表示不被水域覆盖的陆地范围。',
  DEPARE: '水深区域对象，由等深线或 DRVAL1/DRVAL2 深度范围界定；不表示保证水深。',
  DEPCNT: '等深线对象，连接相同水深值（VALDCO）的位置。',
  SOUNDG: '测深点对象，表示单个测深位置的水深值；不表示整片水域可航。',
  FAIRWY: '航道对象，表示供船舶航行的水域范围；实际可航性还需结合水深、碍航物与航海通告。',
  RECTRC: '推荐航路对象，表示主管机关建议的航行路线。',
  NAVLNE: '航行线对象，表示用于导航的线路（如推荐航向或单向航道）。',
  TWRTPT: '双向航路段对象，表示双向航路的一段。',
  CANALS: '运河对象，表示人工开挖的水道。',
  TSSLPT: '分道通航制的航道段对象，属于交通分隔制的一部分。',
  TSSBND: '分道通航制边界对象，用于分隔交通流向。',
  TSEZNE: '分道通航制区域对象。',
  TSSRON: '分道通航制环形道对象，用于船舶转向。',
  CTNARE: '谨慎航行/管制相关区域对象，具体限制需以原始属性为准。',
  DRGARE: '疏浚区域对象，可能标注维护水深；不表示当前保证水深。',
  RESARE: '限制区域对象，具体限制需以 RESTRN 等原始属性为准。',
  ACHARE: '锚地对象，表示船舶可以抛锚的水域。',
  BERTHS: '泊位对象，表示船舶停泊位置。',
  PILPNT: '引航站/引航员登乘点对象。',
  LIGHTS: '灯标对象，表示发光助航标志。',
  WRECKS: '沉船/残骸对象，属于危险物。',
  OBSTRN: '碍航物对象，表示可能影响航行的障碍物。',
}

function normalizeCode(source: string) {
  return source.split(':').pop()?.trim().toUpperCase() || ''
}

export function s57LayerTitle(layer: MapLayerConfig) {
  const candidates = [layer.serviceLayerName, layer.code, layer.name]
  for (const candidate of candidates) {
    const code = normalizeCode(candidate)
    const chineseName = s57ObjectNames[code]
    if (chineseName) return `${chineseName} · ${code}`
  }
  return layer.name
}

export function s57ObjectName(code: string) {
  return s57ObjectNames[code.split(':').pop()?.trim().toUpperCase() || '']
}

export function s57ObjectDescription(code: string) {
  return s57ObjectDescriptions[normalizeCode(code)]
}

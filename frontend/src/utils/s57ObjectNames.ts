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
  FAIRWY: '航道',
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

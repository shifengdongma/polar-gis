/**
 * 后端航路规划结果 — 前端展示契约草案(只读)。
 *
 * 本文件**只有类型与接入说明,没有任何运行时代码**:当前后端没有航路规划接口,
 * 也没有航速 / 船舶参数 / 风险计算服务,所以这里既不发起请求,也不向页面注入
 * 任何演示数值。当前地图工作台不消费本文件的任何类型。
 *
 * 与 RouteDraft 的边界(必须保持):
 * - `RouteDraft` = 用户手绘/输入并保存在 localStorage 的**草稿**,目标是航路点序列;
 * - `RoutePlanningResult` = **后端**算出的只读规划结果,带版本与时间戳;
 * - 两者身份、含义、真值来源都不同,禁止互相赋值或合并成同一个状态对象。
 *
 * 展示原则(接入时必须遵守):
 * 1. 只有 `status === 'complete'` 且对应字段非 null 时才渲染数值;其余状态
 *    (missing / loading / computing / failed / stale)一律只显示状态文案与占位符,
 *    绝不显示 0、也不显示上一次的旧数值当作当前结果;
 * 2. `stale`(结果版本落后于草稿)必须显式告知用户「结果已过期」,而不是静默沿用;
 * 3. `failed` 必须给出失败原因文本,且不保留半截数据;
 * 4. 后端以米 / 秒返回时,展示层统一走 `utils/mapRoute` 的格式化函数
 *    (距离 km + NM、面积 m²/km²),不在组件里各写一套换算。
 *
 * 接入方式(未来):
 * - 实现 `RoutePlanningResultAdapter`,在其中完成**字段校验 + 单位换算 + 时间格式
 *   转换 + 身份区分**;组件只依赖适配后的 `RoutePlanningResult`;
 * - 适配层是唯一允许接触后端原始 payload 的位置,组件不得直接解析响应。
 */

/** 规划结果的生命周期状态 */
export type RoutePlanningStatus =
  /** 尚无结果(未请求 / 后端无此航路) */
  | 'missing'
  /** 已发起请求,等待首个响应 */
  | 'loading'
  /** 后端计算中(异步任务未完成) */
  | 'computing'
  /** 计算失败 */
  | 'failed'
  /** 有结果但已落后于当前草稿(航路点被改动) */
  | 'stale'
  /** 结果可用于展示 */
  | 'complete'

/** 风险等级。当前无风险计算服务,不得在本项目内自行推导 */
export type RoutePlanningRiskLevel = 'unknown' | 'low' | 'medium' | 'high'

/** 分段规划结果(与手绘航段同口径:第 index 段 = 第 index 个点 → 第 index+1 个点) */
export interface RoutePlanningSegmentResult {
  /** 1-based 航段序号 */
  index: number
  distanceMeters: number | null
  durationSeconds: number | null
  riskLevel: RoutePlanningRiskLevel
}

/** 只读的规划结果展示模型(所有数值可为 null —— null 表示「后端未给出」,不是 0) */
export interface RoutePlanningResult {
  /** 对应的手绘草稿 id;用于区分「这条结果属于哪条航路」 */
  routeId: string
  /** 后端结果版本(或算法版本),用于判断过期 */
  resultVersion: string
  /** 结果生成时间(ISO 8601 字符串,展示前由适配层转本地时区) */
  computedAt: string
  status: RoutePlanningStatus
  /** 数据来源标识(如后端服务名 / 版本),用于界面标注出处 */
  dataSource: string
  totalDistanceMeters: number | null
  /** 预计航行时间(秒);需要可靠的航速/船舶参数才可能出现,当前一律 null */
  estimatedDurationSeconds: number | null
  riskLevel: RoutePlanningRiskLevel
  /** 风险指标说明文本(后端给出,前端不生成) */
  riskIndicators: string[]
  segments: RoutePlanningSegmentResult[]
}

/**
 * 接入层契约:后端响应 → 展示模型的唯一入口。
 * 实现方负责字段校验、单位与时间格式转换,并对无法识别的字段给出明确的
 * `status: 'failed'` 而不是静默补默认值。
 */
export interface RoutePlanningResultAdapter {
  fromApiResponse(routeId: string, payload: unknown): RoutePlanningResult
}

/**
 * 展示状态(与 RoutePlanningResult.status 一一对应)。
 * `value` 仅在 complete 时非 null —— 把「没有数值」这件事编码进类型,
 * 避免组件里出现 `result.totalDistanceMeters ?? 0` 这类把缺失当零的写法。
 */
export type RoutePlanningViewState =
  | { status: 'missing' | 'loading' | 'computing' | 'failed' | 'stale'; message: string }
  | { status: 'complete'; value: RoutePlanningResult }

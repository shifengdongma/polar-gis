# 10 — 工作日志 (Work Log)

> 记录每次开发会话的任务计划、修改内容与决策过程
> 最后更新: 2026-10-10

---

## 会话 #27 — 术语修正(海冰浓度→海冰密集度)+ 参考工程目录清理 + 推送

**日期**: 2026-10-10
**背景**: ① 冰情功能中"海冰浓度"为 sea ice concentration 的错误译法,标准术语为"海冰密集度",要求全部修正;② 核实参考工程 `polar-gis-ice-viewer` 的可用代码是否已全部移植,确认后删除该目录以保持项目文件结构标准;③ 最新代码提交并推送 GitHub。

### 一、术语修正(海冰浓度 → 海冰密集度,34 处)

| 文件 | 修改 |
|------|------|
| `backend/app/services/ice.py` | `FIELD_LABELS` 标签 + `warm_default_grid` docstring/注释(3 处) |
| `backend/tests/test_ice_service.py`、`test_ice_api.py` | `/info` label 断言(各 1 处) |
| `frontend/src/utils/mapIce.ts` | `ICE_FIELD_LABELS` + 注释(2 处) |
| `frontend/src/utils/mapIce.test.ts` | fixture label + 用例名(2 处) |
| `frontend/src/composables/useIceOverlay.ts` | 注释(3 处) |
| `frontend/src/components/IceLayerPanel.vue` | 开关名 / 图例标题 / 状态文案「当前日期无浓度数据」→「当前日期无密集度数据」(3 处) |
| `frontend/src/components/IceLayerPanel.test.ts` | 源码断言 + 用例名(3 处) |
| `frontend/src/types/index.ts` | 注释(1 处) |
| `docs/09`、`docs/10`、`docs/11`、`docs/12`、`data/ice/README.md` | 存活文档同步(15 处) |

**范围决策**: 修正对象 = 可加载显示的冰情功能 + 其存活文档;**`docs/plans/` 两份计划期文档(任务书/计划,共 24 处)为冻结历史产物,刻意保持原文**。英文标识层(`concentration` 字段 id / URL 路径 / NetCDF 变量别名)一律不动 —— 接口与数据契约零变化。

### 二、参考工程 `polar-gis-ice-viewer` 清理(源码级核实后删除)

**核实结论**:
1. 核心能力 `backend/app/ice_service.py`(NetCDF 读取 + info/value/alignment/tile + 调色板)已在会话 #26 全量移植为 `backend/app/services/ice.py`,且为**修复版超集**(锁内渲染→锁外、`np.ma.filled(np.asarray())` 丢掩码→显式 getmaskarray+哨兵、value/render 单位口径分裂→单一 `_normalize`、FIFO→LRU、静态索引→重扫+(mtime,size) 失效、硬编码路径→Settings);调色板色值逐值一致;
2. `backend/app/main.py`、`basemap.py`(独立应用壳 + 临时 GeoPackage 海岸线端点)= 原型脚手架,任务书明确不迁移(主系统已有 S-57 底图与完整 API 体系);
3. `frontend/src/App.vue` 的查看器能力(面板/时间轴/浮窗/对齐调试/投影切换)已重实现为 IceLayerPanel/IceTimeline/IceValueTooltip/useIceOverlay;
4. 主仓库对 `polar-gis-ice-viewer` **零代码引用**;该目录是被主仓库 `.gitignore` 排除的**独立 git 仓库**(`https://github.com/shifengdongma/polar-gis-ice-viewer.git`),远端已全量推送、**从未进入主仓库任何提交**(`git log --all -- polar-gis-ice-viewer` 为空)。

**动作**: 删除本地目录(267 MB,含绑定他机的不可用 venv);`.gitignore` 同步移除 `polar-gis-ice-viewer/` 规则。参考代码仍可在其独立 GitHub 仓库查阅,内容可完全恢复。

### 三、验证与推送

- 后端 `pytest`: **214 passed**(与 #26.1 基线一致,零回归);ruff 触碰文件全净
- 前端:`npm run typecheck` 零错误;`npm test` **353 passed**(20 文件,与基线一致);`npm run build` 成功(既有 chunk 体积警告)
- 术语核查:全仓库 `浓度` 仅剩 `docs/plans/` 24 处(冻结文档,刻意保留)
- 浏览器人工验收项(建议):面板开关 / 图例 / hover 浮窗直接目视新术语
- 提交并推送 `master`(CLAUDE.md 工作流)

---

## 会话 #26.1 — 冰情瓦片加载性能修复(请求堆积 / 地图空白 / 时间轴切换不重载)

**日期**: 2026-10-01
**背景**: 用户实测反馈——点开"海冰密集度"后瓦片请求堆积、地图空白卡顿;拖动时间轴切换日期时冰情瓦片"无法重新加载"。要求参照海图瓦片的请求合并/队列等方法优化。

### 一、根因调查(先证据后修复,全部实测)

| 步骤 | 实测结果 |
|---|---|
| E1 冷日期 8 张并发瓦片(修复前) | **每张 6.2–6.8s**,总 7.1s |
| E2 网格已缓存、而片冷 | 8 张共 0.41s(50–120ms/张)→ 慢不在渲染 |
| E3 瓦片+网格全缓存 | 6ms/张 |
| 单张串行冷载基线 | **1.46s**(= 一次完整网格装载成本) |

**根因 ①(后端惊群)**: `_grid` 的缓存检查与落盘之间隔着"归一化在锁外"的窗口,并发首请求各自完整装载 26M 单元网格(N 份冗余 CPU/内存),互相争抢 → 每请求 6.6s。
**根因 ②(前端无管线)**: 冰情走 OL 默认 `<img>` 加载器——无并发上限(整视口瓦片同时发射)、瓦片丢弃不中止(时间轴快拖/切日期后旧请求仍占连接与后端线程)、无共享缓存 → 请求堆积;新日期瓦片排在被卡住的请求后 → "无法重新加载";海图/底图瓦片被挤占 → 地图空白。

另经 ol 10.6 源码核实: `TileState` 枚举没有 `ABORT`,被释放的瓦片经 `release()/dispose()` 置 **`TileState.EMPTY`**(=4);既有海图加载器注释里写的"4=ABORT"称谓有误(值等价,行为正确),冰情加载器统一使用具名 `TileState.EMPTY`。

### 二、修复内容

| 文件 | 修改 |
|------|------|
| `backend/app/services/ice.py` | `_grid` 改为**按日期单飞**:全局锁快路径 + `_grid_locks` per-date 装载锁 + 双检等待者复用;新增 `warm_default_grid()` 由 `info()` 后台守护线程调用(预热默认日期,首次点击即快) |
| `backend/tests/test_ice_service.py` | +4 用例:8 线程并发 `_grid` 只装载一次、8 张并发瓦片(公开路径)只装载一次、warm 幂等、info 触发后台预热 |
| `frontend/src/composables/useIceOverlay.ts` | 新增**自定义 `tileLoadFunction`**(参照海图 `createRetryTileLoadFunction`):共享 `LRUTileCache` + `TileRequestQueue`;缓存优先→限流 fetch→blob;**代次中止** `abortStaleTileLoads()`(refreshLayers 即日期/投影/开关切换时中止上一代全部在飞请求)+ 瓦片 `TileState.EMPTY` 即中止 + 重试;Options 增加 `tileCache`/`tileRequestQueue` 注入;`dispose()` 同步中止 |
| `frontend/src/views/MapWorkspaceView.vue` | 冰情块移至 `tileCache`/`tileRequestQueue` 声明之后(TDZ),注入共享实例 |
| `frontend/src/composables/useIceOverlay.test.ts`、`views/MapWorkspaceView.test.ts` | 隔离断言更新(生命周期状态集合仍禁止;新增"复用管线/代次中止/tileLoadFunction/选项注入"正向断言) |

**决策变更记录**: 任务书 §37 原要求"冰情不接入 TileRequestQueue";本次用户明确要求参照海图请求合并/队列方法解决堆积 → 改为**复用同一套通用请求管线实例**(限流+缓存+中止),但**仍不进入** S-57 图层状态机/Bundle/调度器(该隔离断言保留),docs/09 已同步说明。

### 三、修复后复测(同一真实数据、经 nginx)

- 冷日期 8 张并发瓦片 **7.1s → 3.06s**(每张延迟一致,无饥饿)
- `/info` 后(后台预热生效)全新冷瓦片 **0.13–0.39s**(修复前需 ~2.3s)
- 前端: `npm run typecheck` 零错误;`npm test` **353 passed**(20 文件,349→353);`npm run build` 成功;部署 bundle 已验证含新加载器(`.EMPTY`/`tileLoadFunction`)
- 后端: `pytest` **214 passed**(210→214);ruff 触碰文件干净
- Docker: backend/web 重建成功、全栈健康、经 nginx 实测通过

### 四、已知特性与限制

- 容器重启后**首次** `/info` 在 Windows bind-mount 上约 12s(149 个 HDF5 首次打开;逐日元数据缓存后 **0.1s**);不阻塞地图,预热线程保证首次点击瓦片仍快
- 浏览器 UI 层(points 点击/拖动时间轴的实际观感)仍属人工验收项,本次未执行浏览器自动化
- 按任务书要求,仍未 commit/push

---

## 会话 #26 — 海冰冰情图层完整嵌入(NetCDF → PNG XYZ → 独立 TileLayer)

**日期**: 2026-10-01
**基线**: 分支 `master`,HEAD `593b8da`;工作区起始仅有任务书 md 未跟踪
**任务书**: `docs/plans/Polar-GIS 海冰冰情图层完整嵌入开发任务.md`(48 节,用户提供)
**真实数据**: 用户提供 `F:\polar-gis\sample-data\*.nc` ×149(2022-01-01…2022-05-31,**注意 20220131/20220201 缺文件**),`sic_merged`(int8,units 缺失),4750×5560 网格(1km)、Hughes 极射赤面 **EPSG:3411**、**无厚度变量**(厚度缺失是任务书要求的正常状态)

### 任务计划 (TODO)

| # | 任务 | 状态 |
|---|------|------|
| 1 | 三仓审计(主前端/主后端部署/参考实现)+ 13 问逐项回答 | ✅ 完成 |
| 2 | Phase 0 依赖:`pyproject` + `F:\polar-gis\.venv` 安装 4 个包 | ✅ 完成 |
| 3 | Phase 1 后端:`services/ice.py` + `api/ice.py` + schemas + config + main + 测试(TDD) | ✅ 完成 |
| 4 | Phase 2 部署:data/ice、compose 挂载变量、nginx `^~ /api/`、.env 模板、.gitignore | ✅ 完成 |
| 5 | Phase 3 前端底层:types / api/ice.ts / mapIce.ts / useIceOverlay.ts | ✅ 完成 |
| 6 | Phase 4-6:IceLayerPanel / IceTimeline / IceValueTooltip + hover 优先级 | ✅ 完成 |
| 7 | Phase 7:视图集成(attach/pointermove/投影切换/卸载/菜单/时间轴让位) | ✅ 完成 |
| 8 | Phase 8:全量测试 + Docker 端到端 + 文档 09/10/11/12 | ✅ 完成 |

### 一、审计结论(任务书 13 问)

1. Map 在 `MapWorkspaceView.vue` `buildMap()`(L742+)以 `new OlMap` 创建,`map` 为模块级 `let`(非响应式,组合式函数一律经 getter 访问);
2. EPSG:3413 在视图模块作用域 proj4 注册(L536-538,±4194304 setExtent);**3411 此前全仓库无定义**,前端在 `mapIce.ts` 按需注册 Hughes 定义(与 pyproj EPSG:3411 一致);
3. `switchProjection()`:renderGeneration++ → detach WMS → dispose bundles → 清 tile 缓存/队列 → 切 CRS → setView → fit → reloadAisGeometry → reloadRouteGeometry → syncMeasureForProjection(**本次在其后新增 `iceOverlay.reloadForProjection()`**)→ 重挂 S-57 → reconcile;
4. S-57 RuntimeLayer/Bundle/GWC 生命周期在 attachRuntimeGroups/detachWmsLayer/disposeAllBundles/mapRenderScheduler——冰情全部不触碰(源码断言守护);
5. zIndex:底图 0、S-57 10-40、**航路 95、测量 100、AIS 110**;冰情取 **60/62**(厚度/密集度),调试对齐 120,不改任何现有值;
6. pointermove 消费者仅 1 处(坐标提示 + rAF 合帧)——冰情复用同一分发,不注册第二监听;
7. 截图 `captureMap()` 遍历 `.ol-layer canvas` —— 冰情 TileLayer 天然进入截图;打印隐藏 UI(class `ice-` 与既有 `@media print` 规则);
8. 环境叠加入口在 `.layer-panel-footer` 的 el-dropdown(`handleOverlayCommand('ais')`)——冰情新增 `command="ice"` 项,计数 1→2;
9. 参考读 NetCDF:`netCDF4.Dataset` + 1-D x/y + 别名表 + 整读变量;
10. 参考瓦片:`half=4194304/π·6378137`、像素中心批量变换 → 3411 → 最近邻 → 调色板逐通道插值(含 alpha)→ Pillow RGBA PNG;0 与 NoData alpha 均 0;
11. 参考投影:3411↔4326↔显示投影,**经 WGS84 中转**;3857 纬度钳制 85.05112878;
12. 时间轴:`info.dates` = 实际文件名日期集合,数组索引步进(本数据 20220131/20220201 缺失即真实体现);
13. hover 回源查原始 NetCDF:颜色映射不可逆(NoData/0 透明、alpha 叠加),必须查原始网格值。

### 二、实现记录与参考实现缺陷修复

| 参考实现问题 | 本实现 |
|---|---|
| `_render` 在全局锁内执行(吞吐瓶颈) | 单 RLock **只护 netCDF 访问与缓存变更**,numpy/PIL/pyproj 全部锁外;tile 缓存 FIFO → **LRU**(命中重插) |
| `np.ma.filled(np.asarray(raw), np.nan)` 先丢掩码(thickness 哨兵 9.97e36 会以"有限大数"进入渲染) | `_load_variable`:显式 `getmaskarray` + `_FillValue`/`missing_value` 哨兵置 NaN(**有 float 哨兵与 int 哨兵测试**) |
| `value_at` 返回原始 0-100 而 `_render` 却做 /100(单位不一致) | **唯一归一化入口 `_normalize`**,hover/瓦片共用;concentration 域固定 0-100(不猜单位),thickness cm/mm→m、未知单位不换算(一次性告警) |
| 文件索引构造后不再更新 | `info()` 重扫目录;(mtime,size) 变化的日期逐日期失效 metadata/grid/tile 缓存(有"替换文件后取新值"测试) |
| 硬编码 `F:\workspace\sample-data` | `ICE_DATA_ROOT` 配置(代码中零绝对路径) |
| `int(raw)` 截断 | 保留 float(如实记录偏差);0 有效由 `isIceValueValid` 保障(禁真值判断) |
| 遗留:`value_at` 硬编码 concentration | 增加可选 `field` 参数(默认 concentration,防未来破坏性变更) |

### 三、修改记录

| 文件 | 操作 | 说明 |
|------|------|------|
| `backend/pyproject.toml` | 修改 | +`netCDF4>=1.7,<2`、`numpy>=1.26,<3`、`Pillow>=10,<13`、`pyproj>=3.6,<4`(不加 shapely) |
| `backend/app/core/config.py` | 修改 | +`ice_enabled/ice_data_root/ice_tile_cache_entries/ice_tile_max_zoom` |
| `backend/app/services/ice.py` | 新建 | IceService:日期扫描/别名/归一化/3411→WGS84→显示投影/最近邻瓦片/缓存/降级(线程契约见模块 docstring) |
| `backend/app/api/ice.py` | 新建 | /ice 路由:info/value/alignment/tile;唯一无鉴权数据 API(理由见 docstring);懒工厂 `get_ice_service()` |
| `backend/app/schemas.py` | 修改 | +`IceFieldRead/IceInfoRead/IceValueRead`(value 首字段 + `response_model_exclude_unset` → miss 精确 `{"value": null}`) |
| `backend/app/main.py` | 修改 | 注册 `ice.router, prefix=api` |
| `backend/tests/conftest.py` | 修改 | 前置 `ICE_DATA_ROOT`(测试目录)/`ICE_TILE_MAX_ZOOM` |
| `backend/tests/test_ice_service.py` | 新建 | 31 用例:空目录/损坏文件降级/日期识别排序/别名/跨日期并集/0 有效/127·101·255·负数·NaN NoData/cm·mm·未知单位/哨兵/3413·3857 瓦片/PNG 签名/极点钳制/非法输入/raw value/降序轴/alignment/缓存稳定/文件刷新与替换失效/调色板锁定 |
| `backend/tests/test_ice_api.py` | 新建 | 11 用例:无鉴权 camelCase info/空目录精确响应/value hit+miss 精确契约/422/404 全码/tile PNG+CORS+缓存头/alignment/ICE_ENABLED=false |
| `frontend/src/types/index.ts` | 修改 | +冰情段(IceFieldId/IceFieldInfo/IceInfo/IceValue) |
| `frontend/src/api/ice.ts` | 新建 | fetchIceInfo/fetchIceValue/fetchIceAlignment |
| `frontend/src/utils/mapIce.ts` | 新建 | 纯函数:3411 注册/TileGrid/URL/可用性/日期格式化/范围投影/有效性/索引步进/调色板+图例渐变/字段名 |
| `frontend/src/utils/mapIce.test.ts` | 新建 | 22 用例(调色板与后端逐值锁定;3857 全北半球 y>0 等独立推导) |
| `frontend/src/composables/useIceOverlay.ts` | 新建 | 状态+OL 生命周期(attach 幂等/dispose 彻底/只换源/投影保留状态/hover 契约) |
| `frontend/src/composables/useIceOverlay.test.ts` | 新建 | 13 用例(隔离断言基于去注释代码) |
| `frontend/src/components/IceLayerPanel.vue` + `.test.ts` | 新建 | 面板(6 用例):禁用态/图例同源/免责/定位/调试开关 |
| `frontend/src/components/IceTimeline.vue` + `.test.ts` | 新建 | 时间轴(6 用例):索引驱动/边界/无日期算术/让位注入 |
| `frontend/src/components/IceValueTooltip.vue` + `.test.ts` | 新建 | 浮窗(5 用例):0 有效/翻转/不吞事件 |
| `frontend/src/views/MapWorkspaceView.vue` | 修改 | 集成:imports/iceOverlay/attach/pointermove 分发与提示抑制/pointerleave+卸载清理/switchProjection 同步/环境叠加菜单/模板挂载 |
| `frontend/src/views/MapWorkspaceView.test.ts` | 修改 | +5 集成用例(投影同步/单 pointermove/清理/菜单与时间轴/不进批量卸载) |
| `frontend/src/styles.css` | 修改 | 冰情面板/时间轴/浮窗样式(ice- 前缀)+时间轴打印隐藏 |
| `deploy/compose.yml` | 修改 | `${ICE_DATA_HOST_PATH:-../data/ice}:/data/ice:ro` + `ICE_ENABLED`/`ICE_DATA_ROOT` |
| `deploy/nginx/default.conf` | 修改 | **`location ^~ /api/`**(修 .png 正则拦截) |
| `deploy/.env.example`、`backend/.env.example` | 修改 | ICE_* 模板 |
| `data/ice/README.md`、`data/ice/.gitkeep` | 新建 | 数据目录说明(入库) |
| `.gitignore` | 修改 | `!data/ice/` 白名单 + `data/ice/*.nc` + `sample-data/` + `sample-data.7z` |
| `docs/09/10/11/12` | 修改 | 架构 §5.14 + 文件清单校正、本日志、总结、用户手册 |

### 四、测试结果

- 后端 `pytest`(F:\polar-gis\.venv,**168 → 210**,新增 42:service 31 + api 11);基线 168 全绿不含回归;ruff 本批触碰文件全部干净
- 前端 `npm run typecheck` 零错误;`npm test` **291 → 349**(20 文件,新增 58);`npm run build` 成功
- TDD:后端两模块与前端四模块均先写断言实测 RED(恰为预期失败)再实现转 GREEN
- **Docker 端到端(已执行)**:`docker compose build backend web` 成功(验证 cp312 轮子,**无需新增 apt 包**)→ `up -d` 全部健康 → 经 nginx 真实请求:① `GET /api/v1/health/ready` 正常(回归);② `GET /api/v1/ice/info` 返回 149 个实际日期;③ 瓦片 `.png` 返回 **200 image/png(41,915 B)**;④ `/api/v1/ice/value` 极点返回 `100.0%` 与源坐标
- **`.png` nginx 陷阱已按"先复现后验证"执行**:旧配置(`location /api/`)下同一瓦片 URL 返回 `200 text/html`(SPA index,复现故障);`^~ /api/` 后返回 image/png(非 API 静态 png 仍走正则 location,已验证)
- **真实数据冒烟(已执行)**:info 149 日期 0.89s;hover 极点 100%、冰缘 99%、陆区 0%;瓦片渲染 0.03-0.07s/张;范围外瓦片全透明;**20220131/20220201 缺文件 → 时间轴自然缺两位(真实体现"只展示实际文件日期")**
- **浏览器手工验收(未执行,如实标注)**:tiles 在页面渲染、开关/透明度/时间轴拖动/hover 浮窗/投影切换/截图等 UI 层操作需要人工浏览器操作,本次环境未执行

### 五、关键决策

1. **鉴权边界**:ice 路由整体无鉴权(首个无鉴权数据 API)——OL XYZ `<img>` 无法带 Bearer、地图瓦片同边界、后端仅内网;理由写入 docs/09 与 api/ice.py docstring,避免被误读为漏洞;
2. **懒工厂而非 lru_cache/Depends**:可 monkeypatch、导入期零耦合(冰情失败≠应用失败);
3. **pyproj 共享不加锁**:基于 3.8 源码(thread-local `_Transformer`)与实测(8 线程×200 变换一致),避免给最热 CPU 路径加锁;
4. **NoData/单位单一收口**:hover 与瓦片共用 `_normalize`,并修复参考实现三处真实缺陷;
5. **日期切换只换 Source**:`setSource(new XYZ(...date))` 不重建 layer,`transition:0`;时间轴索引驱动;
6. **`.png` 后缀 + nginx `^~`**:保留任务书主推 URL 形态,顺带加固整个 /api 命名空间;
7. **前端零新增 npm 依赖**:OL/proj4/Vue 均已具备;
8. **提交纪律**:按任务书要求,**本次未执行 git commit / push**,提交信息建议见交付报告。

---

## 会话 #25 — 航路随时点选 + 两侧窗口折叠保障完整地图大屏

**日期**: 2026-10-01
**基线**: 分支 `master`,HEAD `c43c413`,工作区起始干净(`.gitignore` 有一处与本次任务无关的既存改动,随本次提交一并入库,已在提交说明中注明)
**目标**: 完成用户提出的两项修复——① 航路点选不再依赖右侧航路面板打开(随时可点击地图航路查看详情,面板折叠后浮窗保持显示);② 两侧窗口均可折叠以保障完整地图大屏,折叠后航路点选/浮窗仍可用。
**已确认的产品决策(用户选定)**: 折叠 = 完全隐藏 + 常驻按钮恢复(左侧=标题栏按钮,右侧=抽屉 × / 工具栏 🧭,**不新增贴边把手 UI**);折叠右侧窗口时已打开的浮窗**保持显示**。

### 任务计划 (TODO)

| # | 任务 | 状态 |
|---|------|------|
| 1 | 移除航路点选的双重门控(`isSelectionEnabled` 选项 + `singleclick` 面板分支) | ✅ 完成 |
| 2 | `syncRouteFlyout` 不再因面板关闭而关闭浮窗(仅重算锚点让位 540↔16) | ✅ 完成 |
| 3 | 定位让位 padding 随面板折叠状态动态注入(`getFitPadding`) | ✅ 完成 |
| 4 | 可发现性:状态栏提示改为「有可见航路即显示」+ 工具栏 tooltip 更新 | ✅ 完成 |
| 5 | TDD:先写新断言实测 RED,再实现转 GREEN;全套测试 + typecheck + build | ✅ 完成(291 测试) |
| 6 | 文档 09/10/11/12 更新 + git 提交推送 | ✅ 完成 |

### 一、现状核对(已定位的缺陷)

| # | 问题 | 证据 |
|---|------|------|
| 1 | 航路点选被**双重门控**在面板可见性上,面板关闭时点击航线无任何反应 | `MapWorkspaceView.vue` `singleclick` 的 `else if (routePanelVisible.value)` 分支 + `useRouteDrawing` 的 `isSelectionEnabled: () => routePanelVisible.value`(命中函数内二次检查) |
| 2 | 关闭/折叠航路面板**强制关闭**已打开的浮窗 | `syncRouteFlyout()` 关闭条件含 `!routePanelVisible.value` |
| 3 | 折叠两侧窗口后「定位整条航路」仍按 550/420 让位,全屏地图上被挤成窄带 | `fitRoute` 硬编码 `ROUTE_FIT_PADDING = [90, 550, 90, 420]` |
| 4 | 可发现性提示只在面板打开时显示(且此时该提示恰被 520px 抽屉覆盖,实际不可见) | 状态栏 `v-if="routePanelVisible"` |

### 二、修复方式

1. **去门控(点选随时可用)**:删除 `RouteDrawingOptions.isSelectionEnabled`(接口成员 + `pickRouteAtPixel` 内检查)与视图侧注入;`singleclick` 的 `else if (routePanelVisible.value)` → `else`。命中守卫仅剩既有互斥:`interactionMode !== 'idle' || measureMode !== 'none'` 提前返回 + 识别/气象分支优先,语义不变。
2. **浮窗与面板解耦**:`syncRouteFlyout()` 关闭条件去掉 `!routePanelVisible.value`(保留:航路被删除/隐藏、进入绘制编辑态);`routePanelVisible` 保留在浮窗对账 watcher 列表,语义变为「面板折叠/展开时重算锚点让位(540↔16)」。折叠抽屉仍结束绘制/编辑(`watch(routePanelVisible)` 保留不动)。
3. **让位自适应**:`RouteDrawingOptions` 新增可选 `getFitPadding?: () => [上,右,下,左]`;`fitRoute` 改用 `options.getFitPadding?.() ?? ROUTE_FIT_PADDING`;视图注入 `[90, routePanelVisible ? 550 : 40, 90, layerPanelCollapsed ? 40 : 420]`;`ROUTE_FIT_PADDING` 降级为未注入时的默认回退(注释同步)。
4. **可发现性**:状态栏提示改为 `v-if="routesStore.routes.some((route) => route.visible)"`(与面板无关);工具栏 🧭 tooltip 改为「航路规划模拟 · 打开面板绘制/管理航路,地图上随时可点选航路查看详情」。

### 三、修改记录

| 文件 | 操作 | 说明 |
|------|------|------|
| `frontend/src/composables/useRouteDrawing.ts` | 修改 | 删除 `isSelectionEnabled` 门控;新增 `getFitPadding` 选项;`fitRoute` 动态让位;常量与选项注释更新 |
| `frontend/src/views/MapWorkspaceView.vue` | 修改 | `singleclick` 去面板分支;`syncRouteFlyout` 移除面板条件并更新文档注释;`getFitPadding` 注入;状态栏提示与 toolbar tooltip 更新 |
| `frontend/src/views/MapWorkspaceView.test.ts` | 修改 | 重写锁定旧语义的用例(「面板关闭不可选线」)为 4 条新语义断言:无 `isSelectionEnabled`、singleclick 处理函数不含 `routePanelVisible` 且含 `pickRouteAtPixel`、`syncRouteFlyout` 不含 `routePanelVisible` 且仍含 `updateRouteFlyoutPixel()`、提示行不受面板门控且含新 tooltip 文案、`getFitPadding` 已注入 |
| `frontend/src/composables/useRouteDrawing.test.ts` | 新建 | 3 用例源码断言:无任何选择门控;`fitRoute` 使用 `getFitPadding` 且保留 `ROUTE_FIT_PADDING` 回退;默认常量保持 `[90, 550, 90, 420]` |
| `frontend/src/components/RoutePlannerPanel.test.ts` | 修改 | +1 守卫断言:抽屉未禁用自带关闭按钮(`:show-close="false"` 不存在)——折叠路径之一保持可用 |
| `docs/09/10/11/12` | 修改 | 架构 §5.11/§5.12 陈旧表述更新(守卫、生命周期、选线入口、让位)、工作日志、工作总结、用户手册 |

### 四、测试结果

- `npm run typecheck`(vue-tsc -b):零错误
- `npm test`(vitest run):15 个文件 **291** 个测试全部通过(284 → 291,净增 7:重写 1 条 + 新增 6 条)
- `npm run build`:成功(`MapWorkspaceView` chunk 体积警告为既有问题)
- **TDD 过程**:先写 6 条新断言并实测 RED——恰为预期的 6 个失败,全部因功能缺失(而非笔误/正则错误);实现后聚焦文件 GREEN(37 通过),再全套 GREEN
- **浏览器手工验收项(需可运行的前后端环境,本次未执行)**:① 抽屉关闭时点击航路 → 选中 + 浮窗;② 浮窗打开时折叠抽屉 → 浮窗保持显示并重新夹取位置,再展开 → 让位 540;③ 左面板折叠 + 抽屉关闭 → 全屏地图,点选仍可用、「定位整条航路」占满全屏;④ 测量/要素识别/气象/绘制编辑互斥不回归,编辑中折叠抽屉 → 退出编辑;⑤ 点空白只关浮窗不改选中,点另一条航路即时切换;⑥ 投影切换后浮窗重锚定;截图/打印不含浮层

### 五、关键决策

1. **折叠形态 = 完全隐藏 + 常驻按钮恢复**(用户确认):左侧沿用既有标题栏按钮,右侧沿用抽屉 × / 工具栏 🧭;不新增贴边把手 UI,不新增任何折叠状态 ref。
2. **浮窗保持显示**(用户确认):折叠右侧窗口不再关闭浮窗,只在面板开合时重算锚点让位(540↔16);关闭途径为点击地图空白处、浮窗 ×,或进入绘制/编辑态。
3. **门控整体删除而非保留开关**:`isSelectionEnabled` 是唯一门控收口且唯一消费方即本视图,直接删除比留 `() => true` 更难回退,并由源码断言守护防重构回归。
4. **让位自适应而非保留硬编码**:折叠后若仍按 550/420 让位,「定位整条航路」会在全屏地图上挤成窄带,与「完整地图大屏」直接冲突;顺带解除了「抽屉宽度改动须同步常量」的耦合脆弱性(常量注释已改为「默认回退」)。
5. **不新增测量/识别互斥守卫**:点选仍只在「无其他地图交互」时发生——`singleclick` 顶部守卫与识别/气象优先级分支保持原样,本次仅移除面板可见性这一与交互无关的条件。

---

## 会话 #24 — 测量投影审计与修复 + 航段计算 + 航线浮窗 + 坐标悬停提示

**日期**: 2026-09-25
**基线**: 分支 `master`,HEAD `594b47a`,工作区干净(仅 `docs/plans/航路绘制功能优化.md` 未跟踪)
**目标**: 按任务书完成五项任务(任务 E 测量投影审计与修复 → 航段公共计算 → 任务 B 航线信息浮窗 → 任务 A 坐标悬停提示 → 任务 C 航点定位/说明 + 任务 D 后端规划结果契约草案)。全部为纯前端改动,Store 与 localStorage payload 版本零改动。

### 任务计划 (TODO)

| # | 任务 | 状态 |
|---|------|------|
| 1 | 任务 E:实测复核测距/测面积现状(不得未经验证宣称正确或错误) | ✅ 完成 |
| 2 | 任务 E:`utils/mapMeasure.ts` 测地面积算法 + 真值/文本口径 + 单位格式化 | ✅ 完成 |
| 3 | 任务 E:`MapWorkspaceView` 测量投影生命周期 + 互斥缺口修复 + 按钮激活态 | ✅ 完成 |
| 4 | 航段公共计算:`routeSegments` / `initialBearing` / `calculateRouteLength` 重写 | ✅ 完成 |
| 5 | 任务 B:`RouteInfoFlyout.vue` + `pickRouteAtPixel` 命中细节 + 段/点高亮 | ✅ 完成 |
| 6 | 任务 A:rAF 合帧的坐标悬停提示(地面分辨率门槛 + 小数位推导) | ✅ 完成 |
| 7 | 任务 C1/C2/C3:点表两列 + 航点定位 + 单位与免责说明 | ✅ 完成 |
| 8 | 任务 D:`types/routePlanning.ts` 只读展示契约草案 | ✅ 完成 |
| 9 | 单元/源码断言测试 + typecheck + build | ✅ 完成(284 测试) |
| 10 | 文档 09/10/11/12 更新 + git 提交 | ✅ 完成 |

### 一、测距现状审计:实测结论(现状—可复现问题—修复方式—验证结果)

全部结论均由 node 直连**仓库内实际依赖** ol@10.6.1 实测得出,非推测。

#### 现状:不是缺陷的部分(如实记录,不写「已修复」)

| 检查项 | 实测结果 |
|---|---|
| `getLength(geom, {projection: currentCrs})` 的投影参数 | **正确**。`ol/sphere.getLength` 内部先 `clone().transform(P,'EPSG:4326')` 再 haversine;固定 WGS84 点组在 4326 / 3857 / 3413 下均为 `2642270.001110` m(误差 0.0000) |
| 跨 180° 经线的长度 | **正确**。haversine 对 Δλ 取 `sin²`,取短弧天然正确(170E→170W 与参考值一致) |
| `getArea` 对普通多边形 | **正确**。两种投影下与 EPSG:4326 参考完全一致(0.00%) |
| EPSG:3413 是否已注册可转换 | **正确**。`proj4.defs` + `register(proj4)` + `setExtent`,往返误差 0.0000 m |

#### 现状:5 个真实缺陷

| # | 问题 | 证据 / 复现步骤 |
|---|---|---|
| 1 | 测量几何在投影切换后**不重建**、`measureText` **不重算** | 3857 几何被声明为 3413 → **+77.8%**;3413 几何被声明为 3857 → **−1.14%**。复现:测一条线 → 切换投影 → 文本不变、图形错位 |
| 2 | 进行中的测量 Draw **不在投影切换的清理路径上** | 切换后 Draw 仍存活并会 `drawend`,其坐标随后按新 CRS 解释 |
| 3 | 面积**跨 180° 经线偏大约 17 倍** | 20°×6° 盒 @70–76°N 跨 170E..170W:`getArea` 返回 7,371,200 km²,真值 433,600 km² |
| 4 | 面积对**环绕极点**的环返回 **0** | 80°N 环解析真值 3,874,523 km²,`getArea` 返回 0(4/8/36/360 顶点全部为 0)。EPSG:3413 下极点就在屏幕中心,用户**可以**画出这种环 |
| 5 | **互斥缺口**:残余测量 Draw 静默阻塞识别/气象 | `activateMeasure` 不清 `queryMode`/`weatherMode`;`toggleQueryMode`/`toggleWeatherMode` 不调 `stopMeasureInteraction()` → `singleclick` 守卫永久提前 return,点击无任何反馈 |

#### 修复方式

1. **结果与投影解耦(治本)**:新增 `MeasureDraft { kind, lonLat }` WGS84 真值,测量结果文本一律由真值生成,不由「当前投影几何」生成 → 显示值**按构造与投影无关**,整类陈旧 CRS 缺陷消失而非被补丁掩盖。
2. **投影切换生命周期**:`syncMeasureForProjection()`(与 `reloadAisGeometry` / `reloadRouteGeometry` 同范式)——绘制中则结束 Draw + 提示「投影已切换,请重新测量」;已完成则按新投影重建显示几何并从真值重新生成结果。
3. **面积算法替换**:`sphericalRingArea()` 用 Van Oosterom–Strackee 球面三角形立体角 + 0 号顶点扇形三角化(边按大圆,与 `getDistance` 同一球体 `DEFAULT_RADIUS`),取环两侧较小侧。**与经度回绕无关、对环绕极点的环同样成立**,故不再需要「极点检测/拒绝」分支。
4. **drawend 顺序陷阱**:实测 `ol/interaction/Draw.js:1392-1401` 是**先派发 `drawend`、再 `addFeature`** → `drawend` 回调里只落真值与文本,绝不清 source(否则与 OL 随后的 addFeature 撞成重复图形);显示几何重建只发生在投影切换路径。
5. **互斥补齐 + 状态可见**:`measureMode` 成为测量态唯一真值(驱动按钮 `active`、`singleclick` 守卫、Draw 生命周期),两个 toggle 补 `stopMeasureInteraction()`。
6. **无效坐标判定**:实测 `toLonLat` 对 EPSG:3413 越界坐标返回**有限但无意义**的值(不返回 NaN),故用显式范围判定;`EPSG:3857.canWrapX()` 为 true,只校验纬度带。

#### 验证结果(两种投影对照,样例与容差)

| 项目 | EPSG:3857 | EPSG:3413 | 容差 |
|---|---|---|---|
| 测距(固定点组 `10,70 → 30,75 → 50,72 → 20,78`) | `2642.27 km（1426.71 NM）` | `2642.27 km（1426.71 NM）` | 逐字符相同 |
| 测面积(20°×6° 盒 @70–76°N) | `425977.29 km²` | `425977.29 km²` | 逐字符相同 |
| 测地面积 vs 解析闭式(80°N 平行圈 720 顶点) | 3,874,475 vs 3,874,523 km² | 同 | **0.001%** |
| 测地面积 vs 旧 `ol/sphere.getArea`(同高纬盒) | 425,977 vs 433,600 km²(**−1.76%**) | 同 | 小多边形 0.000% |
| 球面 vs WGS84 椭球测地线 | 偏短 **0.28%–0.42%**(高纬更大) | 同 | 按「近似地表距离」表述 |

**复现步骤(修复前 → 修复后)**:① 测距 → 切换投影:修复前文本不变但图形错位、若重算则 +77.8%;修复后图形按新投影重建、文本不变(正确)。② 绘制中切换投影:修复前 Draw 残留且坐标被按新 CRS 解释;修复后 Draw 结束并提示重新测量。③ 在 EPSG:3413 下画一个环绕极点的多边形:修复前面积 0;修复后给出正确非零面积。④ 测量后点「要素识别」:修复前无任何反应(Draw 残留吃掉点击);修复后有反应。⑤ 跨 180° 画多边形:修复前偏大 17 倍;修复后与同形状在常规经度下一致。

### 二、修改记录

| 文件 | 操作 | 说明 |
|------|------|------|
| `frontend/src/utils/mapMeasure.ts` | 新建 | 测量纯逻辑:测地扇形面积、投影↔WGS84 安全换算、真值↔显示几何、结果文本、地面分辨率→小数位门槛 |
| `frontend/src/utils/mapMeasure.test.ts` | 新建 | 23 用例:解析闭式对照、极点环非零(OL 返回 0 的回归守卫)、跨 180° 不变量、投影范围判定、往返、投影无关性 |
| `frontend/src/utils/mapRoute.ts` | 修改 | 新增单位与格式化(km/NM/m²、经纬度文本)、`initialBearing`、`routeSegments`、`shiftCoordinateIntoWorldCopy`、`routePointIndexById`、`unwrapLongitudeSequence`;`calculateRouteLength` 重写为分段和;`RouteStyleContext` 增加可选高亮 getter + 高亮样式 |
| `frontend/src/utils/mapRoute.test.ts` | 修改 | 70 → 100 用例:航段金值/累计/逐位一致、方位角 12 组含 JFK→LHR 外部参考、单位文本、世界副本平移 |
| `frontend/src/components/RouteInfoFlyout.vue` | 新建 | 航线信息浮窗(只读):名称/总长(km+NM)/点数/起终点/可滚动航点表/航段块(段号·距离·累计·初始真方位)/定位操作/免责说明 |
| `frontend/src/components/RouteInfoFlyout.test.ts` | 新建 | 10 用例:内容与只读约束(禁写接口、禁进绘制编辑态)、指针事件与配色一致性、不进入打印 |
| `frontend/src/components/RoutePlannerPanel.vue` | 修改 | 点表新增「入站航段 / 累计」两列(起点显示「—」)、行点击/`#` 按钮定位航点、单位与免责说明、抽屉 440→520px |
| `frontend/src/components/RoutePlannerPanel.test.ts` | 修改 | 6 → 12 用例:两列存在、起点占位符、初始真方位口径、WGS84/1 NM=1852 m 说明、定位路径只读断言、抽屉宽度 |
| `frontend/src/composables/useRouteDrawing.ts` | 修改 | `selectRouteAtPixel` → `pickRouteAtPixel`(顶点/航段命中细节)、`highlightSegment`、`locateRoutePoint`、`getRouteExtent`;fit padding 提为 `ROUTE_FIT_PADDING` 并随抽屉加宽同步为 550 |
| `frontend/src/views/MapWorkspaceView.vue` | 修改 | 测量真值/投影生命周期/互斥修复/按钮激活态;浮层容器 + 浮窗状态与 `postrender` 重锚定;rAF 合帧的坐标悬停提示;可发现性提示 |
| `frontend/src/views/MapWorkspaceView.test.ts` | 新建 | 18 用例源码断言:互斥双向、投影切换同步测量、drawend 不清 source、悬停 rAF/门槛/清理、选线仍走 pickRouteAtPixel |
| `frontend/src/types/index.ts` | 修改 | `RoutePointRoleRow`(派生基类)+ `RoutePointRow` 增加 `inboundLegText` / `cumulativeDistanceText` |
| `frontend/src/types/routePlanning.ts` | 新建 | 任务 D:只读规划结果展示契约草案(纯类型,零运行时/零 API/零演示数据) |
| `frontend/src/styles.css` | 修改 | `.map-overlay-root` / `.map-hover-coord` / `.route-info-flyout` 及航段列、单位说明样式;指针事件与打印规则 |
| `docs/09/10/11/12` | 修改 | 架构 §5.12/§5.13 与文件清单校正、工作日志、工作总结、用户手册 |

### 三、测试结果

- `npm run typecheck`(vue-tsc -b):零错误
- `npm test`(vitest run):14 个文件 **284** 个测试全部通过(197 → 284,新增 87)
- `npm run build`:成功(`MapWorkspaceView` chunk 体积警告为既有问题)

### 四、关键决策

1. **面积语义变更是有据的更正,不是回归**:新算法实现的是 `ol/sphere` 自己文档所称的「大圆边」语义,并与 `getLength` 的大圆语义一致;代价是大范围高纬多边形相对旧值变化 ≤1.76%(小多边形 0.000%),已在文档与界面文案中如实说明。
2. **不引入 `ol/Overlay`**:实测 `ol.css` 无 overlay 容器规则且 OL 以行内样式置 `pointer-events:none`,Overlay 只省下重锚定;浮层改挂 `.map-canvas` 的**兄弟节点**,与既有 `.map-tools`/`.map-status` 同一模式,不往 OL 的 target 里塞 Vue 子节点。
3. **不新增 Select interaction / 第二条航路真值**:选中仍走 `pickRouteAtPixel`;高亮走样式层(可选 getter + 一条带自定义几何的 Style),不新增 source/layer;航路真值仍在 Store,地图 Feature 只负责显示。
4. **保守的面板宽度调整**:点表新增两列后抽屉 440 → 520px,并把 `fitRoute` 的右侧让位提为 `ROUTE_FIT_PADDING` 常量同步到 550,避免定位后航路被抽屉压住。
5. **保持「仅面板打开可选线」**:按任务书,优先采用改动小且体验明确的方案——补工具栏 tooltip 与状态栏提示让该条件可被发现,不自动打开面板、不新增无面板入口。
6. **点表行点击会先排除输入框/按钮**:否则编辑坐标或删除航路点时地图会跟着乱飞。

---
## 会话 #23 — 航路方向标记（起点 / 中途点 / 终点）

**日期**: 2026-09-21
**目标**: 航路绘制需指明航行方向——按途经点先后顺序区分并标记起点与终点。纯前端改动，Store 与 localStorage 持久化格式零改动。

### 任务计划 (TODO)

| # | 任务 | 状态 |
|---|------|------|
| 1 | `mapRoute.ts` 方向角色 `routePointRole` / `routePointRoleLabel`(先红后绿) | ✅ 完成 |
| 2 | `mapRoute.ts` 起点/终点/途经标记样式工厂 `createRoutePointStyles` + 三色常量 | ✅ 完成 |
| 3 | `createRouteStyle` 接入方向标记(起终点常显、途经点选中时显) | ✅ 完成 |
| 4 | `RoutePlannerPanel.vue` 点表「说明」列 + 方向图例 | ✅ 完成 |
| 5 | `styles.css` 角色标签与图例样式(色值与地图标记逐字一致) | ✅ 完成 |
| 6 | typecheck / 全量测试 / build 全绿 | ✅ 完成(197 测试) |
| 7 | 文档 09/10/11/12 更新 + git 提交 | ✅ 完成 |

### 修改记录

| 文件 | 操作 | 说明 |
|------|------|------|
| `frontend/src/utils/mapRoute.ts` | 修改 | 新增 `RoutePointRole` 类型 + `routePointRole()`(按 seq 判定首点=起点/末点=终点/其余=途经)+ `routePointRoleLabel()`;新增 `ROUTE_START_COLOR`/`ROUTE_END_COLOR`/`ROUTE_VIA_COLOR` 与半径常量 + `createRoutePointStyles()`(Point 几何 + 角色化圆形标记,image 按角色缓存);`createRouteStyle()` 接入——起终点标记常显、途经点仅选中且非编辑时显示;`MultiPoint` → `Point` |
| `frontend/src/utils/mapRoute.test.ts` | 修改 | 新增 16 用例:角色判定(空/单点/首末/乱序 seq/越界)+ 中文标注(7);标记工厂(数量/三色/配色池区分/坐标落点/半径/跨航路恒定/空输入)(7);`createRouteStyle` 方向标记三态断言(2,原「选中叠加节点」用例由 3 条样式更新为 4 条) |
| `frontend/src/types/index.ts` | 修改 | 新增 `RoutePointRole` 与 `RoutePointRow`(点表行,派生数据不入 Store) |
| `frontend/src/components/RoutePlannerPanel.vue` | 修改 | 新增 `pointRows` computed(挂载 role/roleLabel,点表数据源改为它);点表新增「说明」列(起点/途经/终点,列标题悬停提示方向规则);详情区底部新增起点/终点图例 + 方向说明 |
| `frontend/src/components/RoutePlannerPanel.test.ts` | 修改 | 新增 4 用例源码断言:「说明」列存在、方向规则文案、图例存在、**图例/CSS 色值必须等于地图标记色常量**(防两套色漂移) |
| `frontend/src/styles.css` | 修改 | 角色标签 `.route-role-tag.is-start/.is-end/.is-via` 与图例 `.route-direction-*` 样式 |

### 测试结果

- `npm run typecheck`(vue-tsc -b):零错误
- `npm test`(vitest run):11 个文件 **197** 个测试全部通过(177 → 197,新增 20)
- `npm run build`:成功(MapWorkspaceView chunk 体积警告为既有问题)

### 关键决策

1. **方向以 `seq` 为真值,不用数组下标**:`routePointRole()` 按 seq 最小/最大判定首末点,与 `buildRouteLineString` 的排序口径完全一致;即便数组顺序被打乱(乱序输入/容错解析),点表标注与地图标记方向也不会分叉(已由用例锁定)。
2. **起点/终点标记常显,途经点仅选中时显示**:方向是航路的固有属性,不选中也应可读;途经点在多航路同显时会铺满屏幕,故沿用原「仅选中显示」策略。编辑态同样保留起终点标记——拖拽节点时方向不丢失。
3. **方向色不取自 8 色配色池**:起点绿 `#2e9e4f`、终点红 `#e5484d` 与配色池(橙/青/蓝/紫/红/沙/绿/浅蓝)刻意分离,避免方向端被线路自身颜色淹没。配色池中的 `#e63946` 与终点红不同色,已由断言区分。
4. **一处定义、两处引用**:颜色常量在 `mapRoute.ts` 定义,`styles.css` 通过**源码断言**(而非 CSS 变量注入)保证逐字一致——panel 测试直接 import 常量与 `styles.css` 比对,色值漂移即测试失败。
5. **几何每帧新建、image 按角色缓存**:标记坐标随视图变化不可复用,必须每帧建 `Point`;但起点/终点颜色与 routeId 无关(恒定),故 `CircleStyle` 按角色缓存跨帧复用,避免 styleFunction 每帧为每点 new 一个圆点样式。
6. **零 Store / 持久化改动**:方向完全由既有 `seq` 推导,未新增字段、未升版本号,旧草稿刷新后自动获得方向标记。

---

## 会话 #22 — 航路面板交互修复：modal-penetrable 指针穿透 + 经纬度范围标注

**日期**: 2026-09-16
**目标**: 修复部署后反馈的 3 个交互问题（地图绘制无效 / 拖拽编辑无效 / 面板打开后地图无法平移缩放）+ 1 个经纬度范围疑问。

### 根因分析（Phase 1）

Element Plus 2.11.5 的 `el-drawer` 设置 `:modal="false"` 只去掉遮罩，抽屉的 overlay 仍渲染为 `position: fixed; inset: 0` 的**全屏 div**（`overlay.mjs` 的 mask=false 分支，无 class 标记），且未设置 `modal-penetrable` 时不会获得 `is-penetrable` 类 → 该 div 拦截**整个视口**的指针事件。地图在 overlay 下层：

1. 平移/缩放收不到 wheel/pointer 事件（问题 3）；
2. "地图绘制/拖拽编辑"按钮都在面板内，面板必须开着才能点击按钮，但随后在地图上的点击被 overlay 吞掉 → Draw 收不到单击加顶点（问题 1）、Modify 收不到拖拽（问题 2）。

**一个根因，三个症状**。EP 官方机制：`modal-penetrable` prop → overlay 获得 `is-penetrable` 类（`pointer-events: none`），仅抽屉面板本身保留交互（`theme-chalk/el-drawer.css` 内置该规则）。

### 任务计划 (TODO)

| # | 任务 | 状态 |
|---|------|------|
| 1 | `RoutePlannerPanel.vue` el-drawer 增加 `modal-penetrable` | ✅ 完成 |
| 2 | 点表列标题标注真实范围（经度 ±180 / 纬度 ±90） | ✅ 完成 |
| 3 | 新增 `RoutePlannerPanel.test.ts` 源码断言回归测试 | ✅ 完成 |
| 4 | typecheck / 全量测试 / build 全绿 | ✅ 完成（177 测试） |

### 修改记录

| 文件 | 操作 | 说明 |
|------|------|------|
| `frontend/src/components/RoutePlannerPanel.vue` | 修改 | el-drawer 增加 `modal-penetrable`；点表列标题标注 `经度(-180~180)` / `纬度(-90~90)` |
| `frontend/src/components/RoutePlannerPanel.test.ts` | 新建 | 源码断言守护 `:modal="false"` + `modal-penetrable` 组合与范围标注 |

### 测试结果

- `npm run typecheck`：零错误
- `npm test`：11 个文件 177 个测试全部通过（新增 2）
- `npm run build`：成功

### 关键决策

1. **经纬度范围并非无意义限制**：经度 ±180、纬度 ±90 是真实地理范围（任务书第五节坐标规则）。经度列本就允许 ±180，±90 只作用于纬度列；用户困惑源于 UI 未标注，已在列标题标明。
2. **修复优先走 EP 官方机制**（`modal-penetrable`），而非自定义 CSS 改 `pointer-events` —— 官方类有对应内置样式与语义，且由源码断言测试防止重构回退。

---

## 会话 #21 — 前端航路规划模拟（绘制/编辑/多航线/投影重建）

**日期**: 2026-09-16
**目标**: 按任务书实现前端航路规划沙箱：经纬度输入绘制、地图自由绘制、拖拽编辑、多航路同显与单条显隐、投影切换重建、localStorage 按项目隔离持久化。纯前端改动，不触碰后端 / S-57 / WMS / GWC / Bundle / TileCache / 调度器；本阶段不新增数据库表，未来以 Route API 替换持久化层。

### 任务计划 (TODO)

| # | 任务 | 状态 |
|---|------|------|
| 1 | `types/index.ts` 追加 RoutePoint / RouteDraft / RouteInteractionMode | ✅ 完成 |
| 2 | `utils/mapRoute.ts` 纯 GIS 模块 + `mapRoute.test.ts` | ✅ 完成（54 用例） |
| 3 | `stores/routes.ts` 航路 Store + `routes.test.ts` | ✅ 完成（22 用例） |
| 4 | `composables/useRouteDrawing.ts` 地图交互（Draw/Modify/重建/定位） | ✅ 完成 |
| 5 | `components/RoutePlannerPanel.vue` + `styles.css` | ✅ 完成 |
| 6 | `MapWorkspaceView.vue` 最小侵入接入（16 处） | ✅ 完成 |
| 7 | typecheck / 全量测试 / build 全绿 | ✅ 完成（175 测试，vue-tsc 零错误） |
| 8 | 文档 09/10/11/12 更新 + git 提交 | ✅ 完成 |

### 修改记录

| 文件 | 操作 | 说明 |
|------|------|------|
| `frontend/src/types/index.ts` | 修改 | 追加 RoutePoint / RouteDraft / RouteInteractionMode 类型 |
| `frontend/src/utils/mapRoute.ts` | 新建 | 校验 / 坐标文本解析（逐行错误）/ normalize / 跨 180° unwrap / 投影转换 / LineString 构建 / 球面长度 / 稳定颜色池 / 样式工厂 / Feature 构建 |
| `frontend/src/utils/mapRoute.test.ts` | 新建 | 54 用例（含测试内注册 proj4 EPSG:3413 的真实变换、跨 180° 经线、round-trip） |
| `frontend/src/stores/routes.ts` | 新建 | Pinia Setup Store：revision 通知计数 + localStorage 按 projectId 隔离 + 全容错解析 |
| `frontend/src/stores/routes.test.ts` | 新建 | 22 用例（CRUD / 显隐 / 持久化恢复 / 项目隔离 / 损坏数据容错） |
| `frontend/src/composables/useRouteDrawing.ts` | 新建 | routeLayer（zIndex 95）/ Draw 草图独立 Collection / Modify 拖拽 / 命中测试选中 / reloadRouteGeometry / fitRoute / dispose |
| `frontend/src/components/RoutePlannerPanel.vue` | 新建 | 非模态 440px 抽屉：新建 / 显隐 / 列表 / 点表 / 地图绘制 / 拖拽编辑 / 批量坐标 |
| `frontend/src/views/MapWorkspaceView.vue` | 修改 | 16 处最小侵入接入（见关键决策） |
| `frontend/src/styles.css` | 修改 | 航路面板样式块 + print 隐藏 |

### 测试结果

- `npm run typecheck`（vue-tsc -b）：零错误
- `npm test`（vitest run）：10 个文件 175 个测试全部通过（新增 mapRoute 54 + routes store 22）
- `npm run build`：成功（MapWorkspaceView chunk 体积警告为既有问题）
- dev server 冒烟：页面 200，MapWorkspaceView / useRouteDrawing / RoutePlannerPanel 模块转换无错误

### 关键决策

1. **草图走独立 Collection**：Draw 使用 `features` 选项而非 `source`——OL 在 drawend 分发后才把草图 push 进目标 source，直写 routeSource 会残留未样式化重复线；Draw 内部 overlay 默认 zIndex 0 会被海图（10-40）盖住，抬到 96。
2. **拖拽安全**：Modify 对 feature 的 change 事件会重建 rBush，拖拽期间 reconcile 短路（isDragging 标志）+ `coordinatesEqual`（1e-6 米容差）短路 setGeometry，保证 Feature 身份稳定、不打断拖拽。
3. **弃 Select interaction**：singleclick 里 `forEachFeatureAtPixel` 命中测试选航路（layerFilter + hitTolerance 6），避免第二套选中状态与测量 Draw 的交互竞争。
4. **revision 计数器代替 deep watch**：20 航路 × 数百点规模下 O(1) 变更检测；zoom/pan 全程 0 次 API / GeoServer 请求（验收项）。
5. **跨 180° 经线**：unwrapLongitudes 仅作用于渲染几何（3857 下 179→-179 展开为 179→181），业务数据永不改写；回写 normalizeLongitude 收拢 ±180；fitRoute extent 平移回投影范围。
6. **抽屉 `:modal="false"`**：默认遮罩会挡住地图绘制/拖拽；关闭面板自动结束航路交互。
7. **`crypto.randomUUID()` 降级**：局域网 http 部署（非安全上下文）下为 undefined，createId() 提供 getRandomValues UUID v4 回退。
8. **投影重建跟随 AIS 范式**：switchProjection 中 `reloadRouteGeometry()` 紧跟 `reloadAisGeometry()`，从 Store WGS84 全量重建，杜绝 3857→3413→3857 累积 transform。

---

## 会话 #20 — WMS 请求合并修复：去重 + 合并键放宽 + 稳健性修复

**日期**: 2026-08-13
**目标**: 会话 #19 的合并方案上线后，批量加载的控制台网络请求仍大量发送（每可见瓦片 ≈ 10 个请求：7 单层 + 3 合并，覆盖相同的 7 个图层）。系统化调试（3 路并行代码探索 + 网络日志分析）定位两大根因 + 5 个附带 bug，逐一修复。

### 根因分析（Phase 1 结论）

1. **请求翻倍（smart 模式）**：`loadResolvedLayersInBatches` 无视 renderMode/bundle 覆盖把全部图层挂为标准 TileWMS 层，随后 `reconcileRenderPlan` 为同样 layerId 建 bundle；调度器 `mapRenderScheduler.ts:436-437` 有意跳过 bundle 覆盖图层的 per-layer 管理 → 批量挂载层永不 detach，与 bundle 并存 → 同一图层每瓦片请求两次（bundle 合并 1.3.0 + 单层 GWC 1.1.1）
2. **合并退化（标准模式）**：合并键含 `styleName`/`objectClass` → 7 个 S-57 对象类 = 7 个单成员组 → 合并器形同虚设；bundle 请求已证明普通 WMS 支持逐层混合 STYLES
3. 附带 bug：detach 残留 LAYERS 参数；重试 off-by-one（3 次而非 2 次）；队列溢出静默丢弃最老（瓦片永不 resolve → 空白）；不可恢复错误不置 ERROR（瓦片卡 LOADING）；`reset()` 清零 inFlight（并发瞬时超限）

### 任务计划 (TODO)

| # | 任务 | 状态 |
|---|------|------|
| 1 | `mapTileMerger.ts` 合并键放宽为 (serviceUrl, renderTransport) + joinLayerParams/globalWmsUrl/toMergeableLayer | ✅ 完成 |
| 2 | `tileRequestQueue.ts` 溢出拒绝最新 + reset 不清 inFlight | ✅ 完成 |
| 3 | `mapRenderScheduler.ts` BundleRenderPlan 暴露 bundledLayerIds | ✅ 完成 |
| 4 | `MapWorkspaceView.vue` smart 去重（预取 plan→跳过覆盖→安全网）+ 合并组生命周期重构 + 三挂载点一致性 + 重试/ERROR 修复 | ✅ 完成 |
| 5 | 测试 + typecheck + build 全绿 | ✅ 完成（99 前端测试，vue-tsc 零错误） |
| 6 | 文档更新 + git 提交 | ✅ 完成 |

### 修改记录

| 文件 | 操作 | 说明 |
|------|------|------|
| `frontend/src/utils/mapTileMerger.ts` | 修改 | 合并键 `{serviceUrl, renderTransport}`（删除 styleName/objectClass）；新增 `MergeableLayer`/`toMergeableLayer`/`joinLayerParams`/`globalWmsUrl`；`effectiveServiceUrl` 加 `ENABLE_GWC_TILES` 门控；组内按 (zIndex, sortOrder, id) 排序；MergeGroup 增加 zIndex；多图层组走 `globalWmsUrl` 全局端点 |
| `frontend/src/utils/tileRequestQueue.ts` | 修改 | 溢出改为拒绝最新请求（QuotaExceededError）；`reset()` 不再清零 inFlight |
| `frontend/src/utils/mapRenderScheduler.ts` | 修改 | `BundleRenderPlan.bundledLayerIds` 字段 + 返回填充 |
| `frontend/src/views/MapWorkspaceView.vue` | 修改 | ①重试守卫 `attempts < TILE_RETRY_MAX_ATTEMPTS` + 不可恢复/重试耗尽 `tile.setState(TileState.ERROR)`；②抽取 `registerMergedGroup`/`syncMergedGroup`/`flushDirtyMergedGroups`/`attachRuntimeGroups`（事件闭包迭代 memberIds）；③detach 组成员 → 微任务合并 `updateParams` 重建；④抽取 `fetchBundlePlanInputFor`（含缓存）；⑤批量加载预取 plan + 被覆盖图层仅登记 + toAttach 过滤 + 每成员缩放；⑥buildMap/模式切换/投影切换统一合并组挂载；⑦executeBundlePlan 安全网 detach 残留 per-layer；⑧layerStatusLabel bundle 覆盖层显示"已显示" |
| `frontend/src/utils/mapTileMerger.test.ts` | **新建** | 17 用例（键/分组/排序/分块/缩放并集/参数拼接/全局 URL/源创建/适配器） |
| `frontend/src/utils/tileRequestQueue.test.ts` | **新建** | 5 用例（溢出拒绝最新/FIFO/reset 计数/abortAll/预中止） |
| `frontend/src/utils/mapRenderScheduler.test.ts` | 修改 | bundle 分支断言 `bundledLayerIds` |

### 测试结果

- 前端 99 个测试全部通过（8 个测试文件；新增 22 用例）
- TypeScript vue-tsc 零错误
- vite build 成功

### 关键决策

1. **updateParams 而非 dispose+recreate**：核对 OL 10.9.0 源码——`updateParams` 执行 `setParams_(Object.assign(this.params_, params))` 并 `changed()` 触发重取（瓦片缓存键含 sourceKey），免重绑三事件、免逐成员 `TileLayer.setSource`；已知限制：多图层组缩至单成员仍走普通 WMS（仅错过 GWC 优化）
2. **"bundle 胜出"双层防线**：批量挂载前预取 plan 排除覆盖图层是主优化；`executeBundlePlan` 安全网 detach 残留 per-layer 是兜底（plan 预取失败等回退路径）
3. **队列溢出拒绝最新**：被拒瓦片转 ERROR → OL 下次渲染自动重取（`ol/ImageTile` ERROR→IDLE）；丢弃最老会永久搁置加载中的瓦片
4. **tile.setState(TileState.ERROR) 而非操作 img**：OL 官方 tileLoadFunction 文档模式，经 `UrlTile.handleTileChange` 派发 `tileloaderror`，三处事件绑定（单层/合并组/bundle）全部自动生效
5. **合并键只保留正确性相关维度**：端点+协议是唯一硬约束；样式/类别/数据集均可共享源（每层 STYLES 位置对齐）

---

## 会话 #19 — WMS 瓦片请求合并（缓解批量加载卡顿）

**日期**: 2026-08-10
**目标**: 标准模式批量加载 100+ 图层后，每次平移触发 1600+ 并发 fetch() 请求 → 合并可共享 TileWMS 源的图层 + 并发限制 + 瓦片缓存

### 任务计划 (TODO)

| # | 任务 | 状态 |
|---|------|------|
| 1 | Component A: LRU 瓦片 Blob 缓存 (`tileCache.ts`) | ✅ 完成 |
| 2 | Component B: 并发请求队列 (`tileRequestQueue.ts`) | ✅ 完成 |
| 3 | Component C: TileWMS 源合并 (`mapTileMerger.ts`) | ✅ 完成 |
| 4 | 文档更新 + TypeScript 验证 + 构建 + 测试 | ✅ 完成 |

### 现象

批量加载 100+ S-57 图层（标准 per-layer 模式）后，每次平移地图触发：`~16 tiles × 100+ layers ≈ 1600+` 并发 `fetch()` /geoserver 请求，远超浏览器 HTTP/1.1 连接池（6-10/域名），导致图层加载缓慢、UI 卡顿、地图大面积空白。

Bundle 模式（智能渲染）已通过逗号分隔 LAYERS 参数合并同 bucket 的多图层请求，但标准模式每层创建一个独立 TileWMS 源，无合并。

### 解决方案（三组件）

**Component A: 瓦片 LRU 缓存** — 避免回访已加载区域重复请求相同瓦片
- 新建 `LRUTileCache` 类（Map 插入顺序实现 O(1) LRU，默认 2048 entries / 50MB）
- `createRetryTileLoadFunction()` 中 fetch 前查缓存命中直接返回 Blob
- 缓存失效：地图销毁、投影切换时 clear()

**Component B: 并发请求队列** — 上限同时进行中的 fetch() 数量
- 新建 `TileRequestQueue` 类（FIFO 队列，默认 maxConcurrent=16，maxQueue=512）
- 支持 AbortSignal（排队中请求可移除；进行中由 fetch signal 中断）
- `createRetryTileLoadFunction()` 中 `fetch()` 替换为 `tileRequestQueue.fetch()`
- 队列只控制并发，不重试（重试由现有 tryLoad setTimeout 递归处理）

**Component C: TileWMS 源合并（核心）** — 同组图层共享一个 TileWMS 源
- 新建 `mapTileMerger.ts`：`groupResolvedLayers()` 按 `(serviceUrl, renderTransport, styleName, objectClass)` 分组；>20 层/组自动分割
- `createMergedTileSource()` 创建逗号分隔 LAYERS/STYLES 的共享源（同 bundle 模式模式）
- `attachWmsLayer()` 新增 `sharedSource?` 参数：传入时跳过源创建和事件接线
- `detachWmsLayer()` 处理合并组成员：最后成员移除时销毁共享源
- `loadResolvedLayersInBatches()` 预分组 + 预创建共享源 + 组级 tile 事件（更新所有成员 runtime）
- Feature flag：`ENABLE_TILE_MERGING`（默认 on，`VITE_ENABLE_TILE_MERGING=false` 关闭）

### 修改记录

| 时间 | 文件 | 操作 | 说明 |
|------|------|------|------|
| 2026-08-10 | `frontend/src/utils/tileCache.ts` | **新建** | LRU 瓦片 Blob 缓存类 |
| 2026-08-10 | `frontend/src/utils/tileRequestQueue.ts` | **新建** | 并发限制请求队列类 |
| 2026-08-10 | `frontend/src/utils/mapTileMerger.ts` | **新建** | 图层分组合并逻辑 + 共享源创建 |
| 2026-08-10 | `frontend/src/utils/mapLayerBatch.ts` | 修改 | 新增 constants：TILE_CACHE_MAX_ENTRIES、TILE_CACHE_MAX_BYTES、TILE_MAX_CONCURRENT_FETCH、TILE_MAX_QUEUED_FETCH；新增 feature flag：ENABLE_TILE_MERGING |
| 2026-08-10 | `frontend/src/views/MapWorkspaceView.vue` | 修改 | imports + `tileCache`/`tileRequestQueue`/`mergedGroupRuntimes`/`mergedGroupMembers` 实例；`createRetryTileLoadFunction` ①查缓存 ②走队列；`attachWmsLayer` 可选 `sharedSource` 参数；`detachWmsLayer` 处理合并组成员（组空则销毁共享源）；`loadResolvedLayersInBatches` 分组模式（预创建共享源 + 组级 tile 事件 + 共享源传递给 attachWmsLayer）；`onBeforeUnmount` 和 `switchProjection` 清缓存+清队列 |

### 测试结果

- 前端：77 passed ✅（所有现有测试通过，无回归）
- TypeScript：vue-tsc 零错误 ✅
- 构建：vite build 成功 ✅

### 关键决策

1. **合并键不含 datasetId**：用 `(serviceUrl, renderTransport, styleName, objectClass)` 更通用——不同数据集的同参数图层也能共享源，效果等同于或优于按数据集分组
2. **GWC 图层单独分组**：GWC 端点 `/gwc/service/wms` + WMS 1.1.1 与普通 WMS `/polar_gis/wms` + 1.3.0 不可混用；`effectiveServiceUrl()` 为 GWC 图层选 `tileServiceUrl`
3. **组级 tile 事件更新所有成员**：共享源加载的每个瓦片覆盖组内所有图层，tileloadstart/end/error 同步更新所有成员 runtimes 的 pendingTiles 和 loadState
4. **队列不做重试**：TileRequestQueue 只控并发，返回原始 Response；retry 逻辑完全由 createRetryTileLoadFunction 的 tryLoad 递归处理，关注点分离
5. **向后兼容**：`ENABLE_TILE_MERGING=false` 时完全回退原逐层行为；所有非批量调用点（单独 toggle、smart standalone）不受影响

---

## 会话 #18.2 — GWC 批量加载 400 修复（图层/样式名 workspace 前缀缺失）

**日期**: 2026-08-10
**目标**: 修复"批量加载图层"后前端报 `400 Bad Request`、图层加载失败

### 现象

浏览器对 `http://localhost:8088/geoserver/gwc/service/wms` 的瓦片请求返回 400，响应体：

```
400: Unknown layer s57_c110408a_1_depare. Check the logfiles, it may not have loaded properly.
```

用正确前缀 `polar_gis:s57_c110408a_1_depare` 重试后进一步暴露：

```
400: Style 's57_depth' is invalid.
```

### 根因分析

1. **会话 #18 优化将 cacheable 图层切换到 GWC WMS facade**（`/gwc/service/wms`，commit 311eb66），批量加载（standard 模式逐层 TileWMS）随之走 GWC 端点
2. **GWC 对图层/样式名做精确匹配**：其注册表键为全限定名（如 `polar_gis:s57_c110408a_1_depare`），裸名请求直接 400；而 GeoServer 自带 WMS 通过默认命名空间解析裸名，所以普通 WMS 路径一切正常——这是 GWC 专属故障
3. **DB 存裸名**：`geoserver_layer_name = code`、`geoserver_style_name = preset.code`，workspace 单独存 `geoserver_workspace`
4. **两个 API 端点返回裸名**：`get_project_dataset_map_layers`（懒加载 toggleDataset 路径，projects.py:226）与 `_build_resolved_layer`（批量 resolve 路径，projects.py:338/362-368）；而 bundle 渲染路径 `_build_layer_render_input`（projects.py:589-600）**早已正确拼接 `workspace:` 前缀**——故智能模式 bundle 正常、批量加载（逐层路径）失败
5. 前端 `MapWorkspaceView.vue:1189` 仅透传后端字段（`geoserverLayerName ?? code`），非缺陷源

### 修改记录

| 时间 | 文件 | 操作 | 说明 |
|------|------|------|------|
| 2026-08-10 | `backend/app/api/projects.py` | 修改 | `get_project_dataset_map_layers`: `service_layer_name` / `style_name` 拼接 `workspace:` 前缀（复用 workspace 变量构建 service_url） |
| 2026-08-10 | `backend/app/api/projects.py` | 修改 | `_build_resolved_layer`: 返回的 `geoserver_layer_name` / `style_name` 拼接 `workspace:` 前缀；本地裸名仅用于 published/loadable 真值判断 |
| 2026-08-10 | `backend/tests/test_projects.py` | 修改 | 两处 `serviceLayerName` 断言更新为全限定名（`polar_gis:demo_depth` / `polar_gis:chart_cell_01_*`），先红后绿 |

### 验证

- 修复后 GWC 请求（`LAYERS=polar_gis:s57_c110408a_1_depare&STYLES=polar_gis:s57_depth`）→ **HTTP 200 PNG 瓦片** ✅
- 普通 WMS 裸名请求 → 200（不受影响）✅
- 后端全量测试：**168 passed** ✅（先改测试见红，再改代码转绿）

### 关键决策

1. **后端拼接前缀（单点修复）**：两处端点 + bundle 路径统一输出 `workspace:name` 全限定名，前端零改动；GeoServer 自带 WMS 接受全限定名，兼容所有 transport
2. 全限定名与 `s57ObjectNames` 的 `split(':').pop()` 归一化逻辑兼容，图层标题显示不受影响
3. 已发布的图层名（GWC 注册表键）即 `polar_gis:xxx` 形式，无需迁移

### 注意

- 修复需重启后端服务（dev `uvicorn --reload` 自动生效；docker 部署需 `docker compose up -d --build backend`）
## 会话 #18.1 — 最终评审修复（SLD 比例尺方向 + Bundle attach 死锁）

**日期**: 2026-08-10
**目标**: 修复整体评审发现的 2 个 Critical + 1 个 Important 缺陷：SLD 比例尺方向反转、Bundle warming 死锁（bundle 永不可见）、被 suspend 的 warming bundle 无法恢复可见

### 根因分析

1. **SLD 方向反转（Critical）**：SLD 规范中 `MinScaleDenominator=25000` 表示"SD ≥ 25000 时规则生效"（缩远方向渲染），而意图是"放大到至少 1:25000 才显示 SOUNDG"（SD ≤ 25000 渲染）。上一批把 classification 的 `minScaleDenominator` 直接作为 `min_scale_denominator` 传入 `render_sld` → 方向相反：缩远全密度渲染（CPU 问题未解决）、放大后高密度层消失（功能性回归）
2. **Bundle warming 死锁（Critical）**：OpenLayers 不可见 TileLayer 不请求瓦片（ol/renderer/Composite.js 可见性门控）。`attachBundle` 创建时 `visible: false` → 无瓦片请求 → 无 tileloadend → status 永远 'warming' → activate 守卫要求 `status === 'active'` 才 setVisible(true) → 永不放行 → bundle 永不可见
3. **被 suspend 的 warming bundle 无法恢复（Important）**：即使 attach 即显示，被 suspend（setVisible false）时仍处于 warming 的 bundle 会再次冻结，activate 守卫必须放宽

### 修改记录

| 时间 | 文件 | 操作 | 说明 |
|------|------|------|------|
| 2026-08-10 | `backend/app/services/s57_style_refresh.py` | 修改 | `sync_s57_layer_style` 以 `max_scale_denominator=min_scale` 调用 `render_sld`（附方向说明注释）；docstring 更新 |
| 2026-08-10 | `backend/app/services/importer.py` | 修改 | `_apply_s57_style` docstring 中 MinScaleDenominator → MaxScaleDenominator |
| 2026-08-10 | `backend/tests/test_s57.py` | 修改 | `test_render_sld_with_min_scale_denominator` → `test_render_sld_with_max_scale_denominator`（锁定向：含 MaxScaleDenominator、不含 MinScaleDenominator） |
| 2026-08-10 | `backend/tests/test_importer.py` | 修改 | 两处生产路径断言 MinScaleDenominator → MaxScaleDenominator（25000.0 / 12345.0） |
| 2026-08-10 | `backend/tests/test_s57_style_refresh.py` | 修改 | 新增方向锁定测试 `test_sld_emits_max_scale_denominator_not_min` |
| 2026-08-10 | `frontend/src/utils/mapRenderBundles.ts` | 修改 | `createBundleTileLayer` `visible: false` → `visible: true`（attach 仅对视口内 bundle 发生；注释说明 tileloadend 仅做状态迁移）；attachBundle/tileloadend 注释更新 |
| 2026-08-10 | `frontend/src/views/MapWorkspaceView.vue` | 修改 | `executeBundlePlan` activate 守卫放宽：`status === 'active'` → 仅拦截 `failed` / `replacing`（修复被 suspend 的 warming bundle 无法恢复可见） |
| 2026-08-10 | `frontend/src/utils/mapRenderBundles.test.ts` | 修改 | TileLayer mock 支持 `getVisible`；新增 `createBundleTileLayer` 可见性测试 |

### 测试结果

- 后端：168 passed ✅（167 → 168，+1 方向锁定测试）
- 前端：77 passed ✅（76 → 77，+1 attach 可见性测试）
- TypeScript：vue-tsc 零错误 ✅
- ruff：触碰文件全部干净 ✅

### 关键决策

1. **SLD 方向修正导致 sldHash 变化是预期行为**：部署后需执行 `POST /api/v1/admin/styles/refresh-s57`，使旧图层重发布（SLD 内容从 MinScale 变 MaxScale）+ truncate GWC 缓存，一次幂等完成
2. **`render_sld` 函数本身不改**：min/max 参数均已支持；仅生产调用路径改用 `max_scale_denominator`

---

## 会话 #18 — 批量加载海图图层渲染性能优化（GWC 3413 链路 + Bundle 修复 + SLD 比例尺 + bbox）

**日期**: 2026-08-10
**目标**: 根治批量加载 160 层海图后平移空白、缩放卡顿问题：接通 GWC EPSG:3413 瓦片缓存全链路，修复前端视口裁剪、Bundle 生命周期、SLD 比例尺与发布 bbox 四类缺陷

### 任务计划 (TODO)

| # | 任务 | 状态 |
|---|------|------|
| 1 | 后端：接通 GWC EPSG:3413 瓦片缓存链路（importer + lifespan backfill + admin 端点） | ✅ 完成 |
| 2 | 后端：导入时持久化 s57.extent 元数据（视口裁剪生效） | ✅ 完成 |
| 3 | 前端：cacheable 图层切换 GWC 瓦片端点 + 字段透传 + ENABLE_GWC_TILES flag | ✅ 完成 |
| 4 | 前端：Bundle 生命周期修复（detach/suspend/activate + renderMode 双向切换） | ✅ 完成 |
| 5 | 后端：SLD 比例尺规则 + sldHash/truncate 幂等刷新 | ✅ 完成 |
| 6 | 后端：发布 feature type 支持真实数据 bbox（仅新发布生效） | ✅ 完成 |
| 7 | 文档更新 + 全量验证 + 提交 | ✅ 完成 |

### 根因分析

批量加载 160 层海图后平移空白、缩放卡顿，根因 5 项：

1. **GWC 缓存全链路未接通**：前端 TileWMS 走普通 WMS（TILED 参数对非 GWC 端点无效）；GWC 只为图层启用 3857/4326 gridset，**EPSG:3413 GridSet 从未创建** → 北极投影下瓦片全部直连 WMS 渲染，无任何缓存命中
2. **前端视口裁剪失效**：`s57.extent` 元数据从未写入 → 160 层全部被视为"在视口内"，超出活动预算，调度器无法正确休眠视口外图层
3. **Bundle 生命周期缺陷**：调度器 bundle 分支 `if (false /* TODO */)` 恒空 → 已挂载 bundle 永不 detach，图层泄漏；renderMode 切换只清不补/只补不清，导致空白或残留
4. **SLD 无比例尺规则**：所有样式在所有缩放级别渲染，高密度图层（SOUNDG 等）小比例尺下也渲染
5. **发布 bbox 硬编码全球**：-180..180 使 GeoServer 查询/渲染扫描范围过大

### 修改记录

| 时间 | 文件 | 操作 | 说明 |
|------|------|------|------|
| 2026-08-09 | `backend/app/services/gwc_backfill.py` | **新建** | `ensure_gridset("EPSG:3413")` 幂等 PUT（extent [-4194304,-4194304,4194304,4194304]）+ `ensure_gwc_layer` 三 gridset（3857/4326/3413）+ `ensure_gwc_3413_backfill()` 纯函数（GET-then-PUT 幂等，`GWC_3413_BACKFILL=0` 跳过） |
| 2026-08-09 | `backend/app/services/importer.py` | 修改 | 发布流程 GWC 启用块抽为 `_enable_gwc_caching`：先 ensure_gridset(EPSG:3413) 再三层 gridset；顺带修复模块级 import 在 logger 之后的问题（E402×11） |
| 2026-08-09 | `backend/app/main.py` | 修改 | lifespan 后台线程 `_spawn_gwc_3413_backfill()`（不阻塞启动）；注册 `system.admin_router` |
| 2026-08-09 | `backend/app/api/system.py` | 修改 | 新增 `admin_router`：`POST /api/v1/admin/gwc/backfill`（require_admin，幂等） |
| 2026-08-09 | `backend/app/api/projects.py` | 修改 | 抽取 `_gwc_transport_for_layer` 共享分类；`GET /map-datasets/{id}/layers` 补 cacheable / render_transport / tile_service_url |
| 2026-08-09 | `backend/app/schemas.py` | 修改 | `MapLayerConfig` 增补 `cacheable` / `render_transport` / `tile_service_url`（可选，向后兼容） |
| 2026-08-09 | `backend/app/core/config.py` | 修改 | 新增 `gwc_3413_backfill`（环境变量 `GWC_3413_BACKFILL`，默认 true） |
| 2026-08-10 | `backend/app/services/importer.py` | 修改 | `merge_s57_layer_metadata` 写入 `s57.extent`（ogrinfo `geometryFields[0].extent`，4 数值校验，NaN/Inf/缺失 → None） |
| 2026-08-10 | `frontend/src/types/index.ts` | 修改 | `MapLayerConfig` 增补 `renderTransport` / `tileServiceUrl` / `cacheable` 三可选字段 |
| 2026-08-10 | `frontend/src/utils/mapLayerBatch.ts` | 修改 | 新增 `ENABLE_GWC_TILES` flag（`VITE_ENABLE_GWC_TILES=false` 回退普通 WMS） |
| 2026-08-10 | `frontend/src/views/MapWorkspaceView.vue` | 修改 | `attachWmsLayer` cacheable 图层切 `/geoserver/gwc/service/wms` + `VERSION: '1.1.1'`（SRS 参数模式）；`loadSelectedDatasets` 透传三字段 |
| 2026-08-10 | `frontend/src/utils/mapRenderScheduler.ts` | 修改 | `RenderPlanInput` 增 `attachedBundleIds`；bundle 分支真实四操作：视口内未挂载 attach / 已挂载 activate / 视口外 suspend / 不在新计划 detach |
| 2026-08-10 | `frontend/src/views/MapWorkspaceView.vue` | 修改 | reconcile 传 `attachedBundleIds`；空计划先 disposeAllBundles；unload 系列（unloadSelectedDatasets / unloadCurrentFilteredLayers / unloadLastBulkBatch）补 reconcile；renderMode watch 双向修复（切 standard 补 attach、切 smart/overview 清 per-layer 残留）；executeBundlePlan activate 守卫（仅 status='active' 才 setVisible） |
| 2026-08-10 | `backend/app/services/s57_styles.py` | 修改 | `render_sld` 支持 `min_scale_denominator` / `max_scale_denominator`（Rule 内、Symbolizer 之前；无参输出与改造前逐字节一致） |
| 2026-08-10 | `backend/app/services/s57_style_refresh.py` | **新建** | `sync_s57_layer_style`：sldHash sha256 对比，变化才 publish + truncate 缓存（`truncate_layer_cache` 复活，best-effort）；`refresh_s57_layer_styles` 批量刷新 |
| 2026-08-10 | `backend/app/api/system.py` | 修改 | 新增 `styles_admin_router`：`POST /api/v1/admin/styles/refresh-s57`（require_admin） |
| 2026-08-10 | `backend/app/services/importer.py` | 修改 | `merge_s57_layer_metadata` 持久化 `s57.minScaleDenominator`；`_apply_s57_style` 委托 `sync_s57_layer_style` |
| 2026-08-10 | `backend/app/services/geoserver.py` | 修改 | `publish_feature_type` / `publish_feature_types_batch` 支持 `bounds` 参数（`_resolve_bounds` 非法值回退全球 -180..180）；`truncate_layer_cache` 复活 |
| 2026-08-10 | `backend/app/services/importer.py` | 修改 | 新增 `_publish_spec_for_layer`：从 `s57.extent` 构建逐层发布 bounds（仅新发布生效） |

### 测试结果

- 后端：167 passed ✅（125 → 167，+42：importer 11 / gwc_backfill 5 / s57_style_refresh 4 / geoserver_publish 15 / projects 3 / test_s57 3 / 端点 1）
- 前端：76 passed ✅（70 → 76，+6：bundle 分支 5 + detach 兜底 1）
- TypeScript：vue-tsc 零错误 ✅
- ruff：本批触碰文件全部干净；全库其余 29 处为改动前已存在的历史 F401 基线（git stash 验证），未触碰

### 关键决策

1. **bundle 保持普通 WMS**：GWC WMS-C 不支持逗号分隔多图层，组合 TileWMS 继续直连普通 WMS；仅 cacheable 单图层切换 GWC 端点
2. **3413 GridSet extent [-4194304,-4194304,4194304,4194304]**：与 OpenLayers 默认 EPSG:3413 瓦片网格对齐，避免双线性重投影额外开销
3. **不做瓦片预热**：缓存自然填充（首次请求渲染 + 写缓存），避免导入期抢资源
4. **已有图层幂等补齐**：`POST /admin/gwc/backfill`（GWC gridset）与 `POST /admin/styles/refresh-s57`（SLD）两个管理员端点；GET-then-PUT / sldHash 对比保证幂等、零重复网络请求
5. **端到端验证由用户在真实 GeoServer 环境执行**：验证方法（curl GWC gridset、X-GWC-Cache 头、160 层平移验证、回退演练）写入"验证方法"而非"已验证"

### 验证方法（真实 GeoServer 环境执行）

```bash
# 1. GridSet 已创建
curl http://localhost:8080/geoserver/gwc/rest/gridsets/EPSG:3413.json
# 2. 图层已启用 3413 gridset（应含 EPSG:3413）
curl http://localhost:8080/geoserver/gwc/rest/layers/polar:{layer}.json
# 3. 瓦片响应带缓存头（X-GWC-Cache: MISS → HIT）
curl -s -o /dev/null -D - "http://localhost:8080/geoserver/gwc/service/wms?LAYERS=polar:{layer}&VERSION=1.1.1&FORMAT=image/png&SRS=EPSG:3413&WIDTH=256&HEIGHT=256&BBOX=..." | grep -i x-gwc-cache
# 4. 批量加载 160 层后平移/缩放验证（活动/休眠统计正常、无空白）
# 5. 回退演练：VITE_ENABLE_GWC_TILES=false 重建前端 → 恢复普通 WMS 行为
```

---

## 会话 #17 — 修复属性表查询失败（column_reference 大小写不匹配）

**日期**: 2026-08-03
**目标**: 修复所有图层"查看属性表"均报"属性表加载失败"的问题

### 任务计划 (TODO)

| # | 任务 | 状态 |
|---|------|------|
| 1 | 诊断属性表查询全链路（前端→后端→SQL） | ✅ 完成 |
| 2 | 修复 column_reference 移除双引号 | ✅ 完成 |
| 3 | 添加 normalize_geo_column_names() 工具函数 | ✅ 完成 |
| 4 | 运行测试 | ✅ 完成 |

### 根因分析

- **DB 验证**: 38,987 层 `allowed_fields` 为大写（如 RCID, PRIM），但 PG 列名均为小写（rcid, prim）
- **SQL 生成**: `column_reference` 使用双引号 `f'"{field}"'` → 生成 `SELECT "RCID"` → PG 大小写敏感 → "column does not exist"
- **回归来源**: commit 441b204 中移除了 `.lower()` 但无数据迁移；旧数据有 UPPERCASE allowed_fields，新 LAUNDER=YES 列是小写
- **错误处理**: PG ProgrammingError 未被 AppError handler 捕获 → HTTP 500 → 前端回退消息"属性表加载失败"

### 修改记录

| 时间 | 文件 | 操作 | 说明 |
|------|------|------|------|
| 2026-08-03 | `backend/app/api/layers.py` | 修改 | column_reference 移除双引号（使用未加引号标识符，PG 折叠为小写）；新增 normalize_geo_column_names() |

### 测试结果

- 后端：125 passed ✅

### 关键决策

- 未加引号 SQL 标识符安全：字段名已由 field_pattern `^[A-Za-z_][A-Za-z0-9_]*$` 严格校验，无 SQL 注入风险
- 不移除双引号 + 更新 allowed_fields 的方案需要 DB migration，而当前方案纯代码层面解决，向后兼容

---

## 会话 #16 — 修复调度器未触发 + 瓦片请求泛滥 + overview死代码

**日期**: 2026-08-03
**目标**: 修复三个遗留问题：活动/休眠/等待始终为0、底图空白、后续图层加载不出

### 任务计划 (TODO)

| # | 任务 | 状态 |
|---|------|------|
| 1 | 批量加载后调用 reconcileRenderPlan 填充调度器状态 | ✅ 完成 |
| 2 | tileLoadFunction 加 AbortController + 修正 .catch() 重试范围 | ✅ 完成 |
| 3 | SMART_MAX_ACTIVE_WMS_LAYERS 30→20 | ✅ 完成 |
| 4 | 实现 setOverviewVisible（替代空实现） | ✅ 完成 |
| 5 | 新增 SMART_MAX_UNBOUNDED_ACTIVE=10 限制无范围图层占用 | ✅ 完成 |

### 修改记录

| 时间 | 文件 | 操作 | 说明 |
|------|------|------|------|
| 2026-08-03 | `frontend/src/views/MapWorkspaceView.vue` | 修改 | 4处：batch后调用reconcile；tileLoadFunction加AbortController+修正重试；setOverviewVisible实现 |
| 2026-08-03 | `frontend/src/utils/mapLayerBatch.ts` | 修改 | SMART_MAX_ACTIVE_WMS_LAYERS 30→20；新增 SMART_MAX_UNBOUNDED_ACTIVE=10 |
| 2026-08-03 | `frontend/src/utils/mapLayerBatch.test.ts` | 修改 | 更新常量测试 |
| 2026-08-03 | `frontend/src/utils/mapRenderScheduler.ts` | 修改 | import/export SMART_MAX_UNBOUNDED_ACTIVE；buildRenderPlan中增加无范围图层计数和预算 |
| 2026-08-03 | `frontend/src/utils/mapRenderScheduler.test.ts` | (no changes) |

### 根因分析

1. **调度器未触发**：批量加载直接调用 attachWmsLayer + setVisible(true)，从未调用 reconcileRenderPlan。activeLayerIds/suspendedLayerIds/warmingLayerIds 三个 Set 仅由 executePerLayerPlan 填充。
2. **底图空白**：fetch() 无 AbortController → 平移时僵尸请求持续占用连接池；.catch() 对所有错误无条件重试 → 重试雪崩；30活动层×20瓦片=600并发请求 → 底图图片加载饿死。
3. **后续图层不加载**：(a) null extent 图层永久占用活动预算；(b) 首轮 reconcile 会将超出预算的图层全部 suspend；(c) 激活已attach图层需要第二次 reconcile 触发。

### 测试结果

- 前端：70 passed ✅
- TypeScript：vue-tsc zero errors ✅

---

## 会话 #15 — 批量加载后优化：warming队列修复 + SOUNDG移除 + UI修复

**日期**: 2026-08-03
**目标**: 修复批量加载后的三个问题：缩放后图层切换失效、数据集展开状态、SOUNDG从核心图层移除

### 任务计划 (TODO)

| # | 任务 | 状态 |
|---|------|------|
| 1 | 后端：SOUNDG 从 CORE_CHART 移到 OPTIONAL_THEMATIC | ✅ 完成 |
| 2 | 后端：更新测试（catalog + bundle + resolve） | ✅ 完成 |
| 3 | 前端：修复 warming 队列永不排空的关键 Bug | ✅ 完成 |
| 4 | 前端：批量加载后数据集展开状态修复 | ✅ 完成 |
| 5 | 前端：辅助性能优化（API 缓存/loadProfile/Set 批量化） | ✅ 完成 |
| 6 | 前端：修复两个测试用例的过期常量值 | ✅ 完成 |

### 修改记录

| 时间 | 文件 | 操作 | 说明 |
|------|------|------|------|
| 2026-08-03 | `backend/app/services/s57_layer_catalog.py` | 修改 | SOUNDG 从 _CORE_CHART_RULES 移到 OPTIONAL_THEMATIC |
| 2026-08-03 | `backend/tests/test_s57_layer_catalog.py` | 修改 | EXPECTED_CORE_CHART 移除 SOUNDG；EXPECTED_OPTIONAL_THEMATIC 添加 SOUNDG；更新 display_priority/category 断言 |
| 2026-08-03 | `backend/tests/test_map_render_plan.py` | 修改 | 更新 SOUNDG 的 display_category 测试参数和 categories/objects fixture |
| 2026-08-03 | `frontend/src/views/MapWorkspaceView.vue` | 修改 | 6 处变更见下方详细说明 |
| 2026-08-03 | `frontend/src/utils/mapLayerBatch.test.ts` | 修改 | 更新 SMART_MAX_* 常量的过期望值（20→30, 3→10, 40→60） |
| 2026-08-03 | `frontend/src/utils/mapRenderScheduler.test.ts` | 修改 | 修复 test 26 的排序断言以适配 warming=10 预算 |

### 关键 Bug 修复：warming 队列永不排空

根因：`warmingLayerIds` 仅在 `attachWmsLayer` 中添加、`detachWmsLayer` 中移除，但首块瓦片成功加载（tileloadend）后从不移除。这导致 `warmingLayerIds.size === 10` 永久保持，调度器 gate `warming.length + currentWarmingCount < SMART_MAX_WARMING_LAYERS` 永久拒绝所有后续 attach。

修复：
1. `tileloadend`/`tileloaderror` 回调中：`pendingTiles === 0` 时从 warmingLayerIds 移除
2. `reconcileRenderPlan` 开头：扫描 warming 超时（`TILE_WARMING_TIMEOUT_MS=15s`）图层并排空
3. 新增 `layerWarmingStartTime` Map 记录进入 warming 的时间

### MapWorkspaceView.vue 变更汇总

1. **warming 排空**：tileloadend/tileloaderror 中当 pendingTiles 归零时移除 warmingLayerIds 条目
2. **warming 超时**：reconcileRenderPlan 中扫描超时 warming 图层
3. **数据集展开**：批量加载后标记 `dataset.loaded = true`；toggleDataset 跳过已加载数据集的 API 重取
4. **已加载计数**：数据集摘要行显示"已加载 N 个"
5. **loadProfile 传递**：resolve 结果中的 loadProfile 写入 config.metadata.s57
6. **Set 批量化**：executePerLayerPlan 中 suspend/attach/activate 的 Set 操作收集后一次性更新
7. **Bundle API 缓存**：按 (sorted layerIds + projection) 缓存 bundle plan，避免每次 moveend 请求

### 测试结果

- 后端：125 passed ✅
- 前端：70 passed, vue-tsc clean ✅

### 关键决策

1. SOUNDG 移至 OPTIONAL_THEMATIC 后，display_category 变为 `"optional_thematic"`，display_priority 变为 `100`，recommended 变为 `False`。_SCALE_RULES 和 _OBJECT_BUCKET_OVERRIDES 保留不变。
2. warming 排空采用事件驱动（tileloadend）+ 超时兜底（15s）双保险
3. 不自动展开批量加载的数据集面板，仅标记 `loaded=true` 并显示计数，用户手动控制展开

---

## 会话 #14 — 提高批量加载图层上限至160

**日期**: 2026-08-03
**目标**: 将批量加载图层硬限制从120提高到160

### 任务计划 (TODO)

| # | 任务 | 状态 |
|---|------|------|
| 1 | 修改前端 BULK_HARD_LIMIT 常量 (120→160) | ✅ 完成 |
| 2 | 修改后端 schema max_length (120→160) | ✅ 完成 |
| 3 | 更新前端单元测试 | ✅ 完成 |
| 4 | 验证测试通过 | ✅ 完成 |

### 修改记录

| 时间 | 文件 | 操作 | 说明 |
|------|------|------|------|
| 2026-08-03 | `frontend/src/utils/mapLayerBatch.ts` | 修改 | BULK_HARD_LIMIT 120 → 160 |
| 2026-08-03 | `backend/app/schemas.py` | 修改 | MapRenderPlanRequest.layer_ids max_length 120 → 160 |
| 2026-08-03 | `frontend/src/utils/mapLayerBatch.test.ts` | 修改 | 测试用例阈值 120/121 → 160/161 |

---

## 会话 #13 — Phase 1: 组合图层渲染通道 (Composite Layer Render Bundles)

**日期**: 2026-08-02
**目标**: 在智能模式下将 20~30 个独立 TileWMS 图层压缩为约 3~6 个语义组合 TileWMS，大幅减少 HTTP 瓦片请求数量

### 任务计划 (TODO)

| # | 任务 | 状态 |
|---|------|------|
| 1 | 后端 Pydantic Schema (MapRenderPlanRequest/Response) | ✅ 完成 |
| 2 | 后端 API 端点 POST /map-render/plan | ✅ 完成 |
| 3 | 后端 API 集成测试 | ✅ 完成 |
| 4 | 前端 TypeScript 类型定义 | ✅ 完成 |
| 5 | 前端 Bundle 运行时 (mapRenderBundles.ts) | ✅ 完成 |
| 6 | 前端 API Client (fetchRenderPlan) | ✅ 完成 |
| 7 | 前端 Scheduler 集成 (BundleRenderPlan) | ✅ 完成 |
| 8 | MapWorkspaceView.vue Bundle 执行路径 | ✅ 完成 |
| 9 | Feature Flag (VITE_ENABLE_RENDER_BUNDLES) | ✅ 完成 |
| 10 | 前端 Bundle 单元测试 | ✅ 完成 |

### 修改记录

| 时间 | 文件 | 操作 | 说明 |
|------|------|------|------|
| 2026-08-02 | `backend/app/schemas.py` | 修改 | 新增 MapRenderPlanRequest, BundleConfigOut, StandaloneConfigOut, RenderPlanSummaryOut, MapRenderPlanResponse 五个 Pydantic Schema |
| 2026-08-02 | `backend/app/api/projects.py` | 修改 | 新增 POST /{project_id}/map-render/plan API 端点，复用 _s57_object_class, _style_mapped_for_layer, classify_s57_layer 工具函数，调用 build_bundles() 纯函数 |
| 2026-08-02 | `backend/tests/test_projects.py` | 修改 | 新增 6 个 render plan API 集成测试 (非项目图层拒绝、打包分组、多桶分离、非空间排除、确定性 cache key、空输入) |
| 2026-08-02 | `frontend/src/types/index.ts` | 修改 | 新增 RenderBundleConfig, StandaloneLayerConfig, RenderPlanSummary, MapRenderPlanRequest, MapRenderPlanResponse, BundleViewState 类型 |
| 2026-08-02 | `frontend/src/utils/mapRenderBundles.ts` | **新建** | Bundle 运行时管理: createBundleTileSource, attachBundle, detachBundle, replaceBundle (原子替换), setBundleVisible, disposeAllBundles, findBundleByLogicalLayer |
| 2026-08-02 | `frontend/src/api/projects.ts` | 修改 | 新增 fetchRenderPlan() API client 函数 |
| 2026-08-02 | `frontend/src/utils/mapRenderScheduler.ts` | 修改 | 新增 BundleRenderPlan 接口, ENABLE_RENDER_BUNDLES Feature Flag, buildRenderPlan() 增加 bundlePlanInput 参数和 bundle-aware 执行路径 |
| 2026-08-02 | `frontend/src/views/MapWorkspaceView.vue` | 修改 | reconcileRenderPlan() 改为 async，smart 模式自动调用 fetchRenderPlan；新增 executeBundlePlan() 和 executePerLayerPlan()；toggleLayer() 支持 Bundle 模式延迟重建；switchProjection() 增加 disposeAllBundles；unloadAllChartLayers() 增加 Bundle 清理 |
| 2026-08-02 | `frontend/src/utils/mapRenderBundles.test.ts` | **新建** | 11 个单元测试: TileWMS 创建、comma-separated LAYERS/STYLES、URL 转换、配置校验、桶分离验证 |

### 决策记录

1. **后端纯函数服务已存在**: `map_render_plan.py` 和 `test_map_render_plan.py` (32 个测试) 在本次会话前已实现，只需新增 API 端点和 Schema
2. **Feature Flag 默认启用**: `ENABLE_RENDER_BUNDLES` 默认为 `true`，设置 `VITE_ENABLE_RENDER_BUNDLES=false` 可回退到独立 WMS 模式
3. **Bundle 原子替换**: 切换 Bundle 时旧 Bundle 保持可见直到新 Bundle 首块瓦片加载成功，失败则保留旧 Bundle
4. **Standalone 图层**: opacity ≠ 1.0 或 renderStandalone=true 的图层自动从 Bundle 中提升为独立 TileWMS
5. **无数据库迁移**: 本次变更纯加法 — 新增 API 端点、前端工具模块和类型定义，不涉及数据库或 GeoServer 资源变更

### 验证结果

- Backend: 44 tests passed (32 map_render_plan + 12 projects)
- Frontend: 11 tests passed (mapRenderBundles)
- TypeScript type check: clean (no errors)
- Feature Flag: SET VITE_ENABLE_RENDER_BUNDLES=false for rollback

---

## 会话 #12 — 海图批量加载前端显示性能优化

**日期**: 2026-07-28
**目标**: 分析批量导入 S-57 海图图层后页面加载缓慢和地图卡顿的根因，在不改变现有功能和代码结构的基础上优化前端显示性能

### 任务计划 (TODO)

| # | 任务 | 状态 |
|---|------|------|
| 1 | 调整智能调度器预算常量 (SMART_MAX_*) | ✅ 完成 |
| 2 | Set 状态改用 shallowRef 减少响应式开销 | ✅ 完成 |
| 3 | WMS 图层动态 zIndex 排序 | ✅ 完成 |
| 4 | 实现 tileLoadFunction 瓦片加载重试 | ✅ 完成 |
| 5 | nginx 启用 HTTP/2 | ✅ 完成 |
| 6 | nginx WMS 瓦片 proxy_cache | ✅ 完成 |
| 7 | 静态资源缓存头 (Cache-Control) | ✅ 完成 |
| 8 | 导入后创建 PostGIS 空间索引 + ANALYZE | ✅ 完成 |
| 9 | 标准导入自动启用 GWC 瓦片缓存 | ✅ 完成 |
| 10 | GeoServer JVM 调优 | ✅ 完成 |

### 修改记录

| 时间 | 文件 | 操作 | 说明 |
|------|------|------|------|
| 2026-07-28 | `frontend/src/utils/mapLayerBatch.ts` | 修改 | 调度器常量调整: SMART_MAX_WARMING_LAYERS 3→10, SMART_MAX_ACTIVE_WMS_LAYERS 20→30, SMART_MAX_ATTACHED_WMS_LAYERS 40→60 |
| 2026-07-28 | `frontend/src/views/MapWorkspaceView.vue` | 修改 | (1) 7个 Set 状态从 ref() 改为 shallowRef() 减少深层响应式追踪开销; (2) 新增 layerZIndex() 函数按 S-57 对象类分类设置图层 zIndex; (3) 新增 createRetryTileLoadFunction() 用 fetch+指数退避实现瓦片加载重试 |
| 2026-07-28 | `deploy/nginx/default.conf` | 修改 | (1) listen 增加 http2 启用 HTTP/2 多路复用; (2) 新增 proxy_cache_path + proxy_cache 指令缓存 GeoServer 瓦片; (3) 新增静态资源 Cache-Control 头 (hashed资源1y immutable, index.html no-cache) |
| 2026-07-28 | `deploy/compose.yml` | 修改 | GeoServer 添加 INITIAL_MEMORY/MAXIMUM_MEMORY/JAVA_OPTS JVM 调优环境变量 |
| 2026-07-28 | `backend/app/services/importer.py` | 修改 | (1) 导入后为每张 geo.* 表创建 GiST 空间索引并运行 ANALYZE; (2) 发布阶段自动调用 ensure_gwc_layer() 启用瓦片缓存; (3) 添加 logging 模块 |

### 问题分析与发现

通过前端、后端、部署三个维度的全面审查，确认了以下核心瓶颈:

1. **前端**: TileWMS 源未设置 tileLoadFunction 导致瓦片加载无重试; 所有图层 zIndex: 10 导致绘制顺序不稳定; ref(new Set()) 对每个元素深层追踪产生不必要的响应式开销; 暖机预算 3 层过保守
2. **基础设施**: nginx 无 HTTP/2 (浏览器 6 连接限制成为瓦片加载天花板); 无 nginx 瓦片缓存; 静态资源无缓存头
3. **后端**: 导入后无 PostGIS 空间索引 (GeoServer 顺序扫描); GWC 未自动启用; GeoServer 无 JVM 调优

### 关键决策

1. 优化原则: 不改变现有功能、代码结构和加载原理; 批量解析→候选过滤→分批附加流程不变; 三种渲染模式不变
2. 优先前端 + 基础设施改动 (直接改善瓦片加载体验)
3. Layer zIndex 基于 S-57 对象类语义分层: 填充层(10)→等深线(20)→岸线(25)→危险物(30)→水深点(35)→助航标志(40)

## 会话 #1 — 项目初始化与环境配置

**日期**: 2026-07-20
**目标**: 初始化项目开发环境, 创建规范文档, 配置 Git 远程仓库, 安装依赖, 启动项目

### 任务计划 (TODO)

| # | 任务 | 状态 |
|---|------|------|
| 1 | 创建 CLAUDE.md 项目规范文件 | ✅ 完成 |
| 2 | 创建 docs/09-system-architecture.md 系统架构文档 | ✅ 完成 |
| 3 | 创建 docs/10-work-log.md 工作日志文档 | ✅ 完成 |
| 4 | 创建 docs/11-work-summary.md 工作总结文档 | ✅ 完成 |
| 5 | 配置 Git 远程仓库 + 初始提交 + 推送 | ✅ 完成 |
| 6 | 创建 .venv 虚拟环境 + 安装 Python 依赖 | ✅ 完成 |
| 7 | 配置 Docker Compose 环境并启动 | ✅ 完成 |
| 8 | 验证服务健康状态 | ✅ 完成 |
| 9 | 更新文档并提交最终版本 | ✅ 完成 |

### 修改记录

| 时间 | 文件 | 操作 | 说明 |
|------|------|------|------|
| 2026-07-20 | `CLAUDE.md` | 新建 | 项目规范: 虚拟环境路径、文档规约、Git工作流 |
| 2026-07-20 | `docs/09-system-architecture.md` | 新建 | 系统架构文档: 前后端代码结构、API路由、数据模型、部署架构 |
| 2026-07-20 | `docs/10-work-log.md` | 新建 | 工作日志文档 (本文件) |
| 2026-07-20 | `docs/11-work-summary.md` | 新建 | 工作总结文档 |
| 2026-07-20 | `deploy/compose.yml` | 修改 | GeoServer版本 2.26.2→2.25.3 (使用本地缓存镜像); 移除version字段; backend/worker改用预构建镜像; web改用预构建镜像 |
| 2026-07-20 | `backend/Dockerfile` | 修改 | apt-get增加 --fix-missing 参数以应对网络不稳定 |
| 2026-07-20 | `frontend/Dockerfile` | 修改 | node版本 22-alpine→20-alpine (使用本地可用镜像) |
| 2026-07-20 | `backend/migrations/versions/0003_project_code_active_unique.py` | 修复 | 使用 IF NOT EXISTS 避免重复创建索引错误 |
| 2026-07-20 | `deploy/.env` | 新建 | 从 .env.example 复制, 使用默认开发配置 |

### 遇到的问题与解决方案

1. **docker.osgeo.org 不可达**: DNS超时 + TLS握手超时 → 使用本地已有的 geoserver:2.25.3 镜像
2. **daocloud镜像不稳定**: 部分Docker Hub镜像401/EOF → 使用预构建镜像策略
3. **Debian包下载失败**: 网络不稳定导致2个包下载失败 → 增加 --fix-missing 参数
4. **Alembic迁移0003失败**: uq_projects_code_active索引已存在 → 添加IF NOT EXISTS

### 环境信息

- **开发机**: Windows 11 Home China 10.0.26200
- **Python**: 3.12.7
- **Node.js**: v22.14.0
- **Docker Desktop**: 29.6.1 + Compose v5.2.0
- **项目路径**: `F:\polar-gis\`
- **GitHub 仓库**: https://github.com/shifengdongma/polar-gis.git

### 服务运行状态

| 服务 | 端口 | 状态 |
|------|------|------|
| PostgreSQL + PostGIS | 5432 | ✅ healthy |
| GeoServer | 8080 | ✅ healthy |
| Backend (FastAPI) | 8000 (内部) | ✅ healthy |
| Worker | - (内部) | ✅ running |
| Web (Nginx + Frontend) | 8088 | ✅ running |

---

## 会话 #2 — 修复登录 401 错误

**日期**: 2026-07-20
**目标**: 诊断并修复 admin 用户登录报 401 Unauthorized 错误

### 任务计划 (TODO)

| # | 任务 | 状态 |
|---|------|------|
| 1 | 诊断登录 401 错误原因 | ✅ 完成 |
| 2 | 修复数据库中的 admin 账户状态 | ✅ 完成 |
| 3 | 验证修复结果 | ✅ 完成 |

### 修改记录

| 时间 | 文件 | 操作 | 说明 |
|------|------|------|------|
| 2026-07-20 | (数据库) | 修改 | 重置 admin 用户: failed_login_count→0, locked_until→NULL, 更新 password_hash |

### 问题诊断

1. **账户锁定**: admin 用户 failed_login_count=5, locked_until 已设置 — 因多次密码错误被锁定15分钟
2. **密码可能不匹配**: .env 中 INITIAL_ADMIN_PASSWORD 与数据库中哈希不一致
3. **429 Too Many Requests**: 锁定后继续尝试导致触发 rate limiting

### 解决方案

直接在 PostgreSQL 中更新 users 表:
- 重置 `failed_login_count = 0`
- 清除 `locked_until = NULL`
- 使用 Argon2 重新哈希密码并更新 `password_hash`

### 知识点

- `.env` 修改后不需要重新构建镜像, `docker compose down && docker compose up -d` 重启即可
- `ensure_initial_admin()` 仅在用户不存在时创建, 不会更新已存在用户的密码
- 因此改密码需要同步更新数据库, 或删除用户后重启让系统重建

---

## 会话 #3 — 生成用户操作使用手册

**日期**: 2026-07-21
**目标**: 全面分析项目代码文件与功能, 生成一份完整详细的用户操作使用手册

### 任务计划 (TODO)

| # | 任务 | 状态 |
|---|------|------|
| 1 | 分析后端 API 结构 (71 个端点) | ✅ 完成 |
| 2 | 分析前端视图与路由 (10 个页面组件) | ✅ 完成 |
| 3 | 分析后端服务与 Worker | ✅ 完成 |
| 4 | 分析部署配置与现有文档 | ✅ 完成 |
| 5 | 撰写用户手册 (9 大章节) | ✅ 完成 |
| 6 | 更新文档 09/10/11 并提交推送 | ✅ 完成 |

### 修改记录

| 时间 | 文件 | 操作 | 说明 |
|------|------|------|------|
| 2026-07-21 | `docs/12-user-manual.md` | 新建 | 完整用户操作使用手册: 系统概述、安装部署、快速入门、用户界面指南、管理功能指南、数据格式、API参考、常见问题、附录 |
| 2026-07-21 | `docs/09-system-architecture.md` | 修改 | 更新文档索引, 添加用户手册引用 |
| 2026-07-21 | `docs/10-work-log.md` | 修改 | 添加会话 #3 工作日志 |
| 2026-07-21 | `docs/11-work-summary.md` | 修改 | 添加会话 #3 工作总结 |

### 手册内容概览

手册共 9 大章节, 覆盖:

1. **系统概述**: 平台简介、核心特性、技术架构、用户角色
2. **安装与部署**: 环境要求、Docker Compose 部署、运维命令、开发环境
3. **快速入门**: 首次登录、典型工作流程、一分钟体验
4. **用户界面指南**: 登录认证、项目门户、地图工作台(图层面板/地图工具/投影切换/属性表/导出)
5. **管理功能指南**: 管理仪表盘、用户管理、项目管理(生命周期/图层配置)、数据目录(上传/版本管理/批量删除)、S-57批量导入、导入任务监控、数据清理、图层与系统管理(图层/SLD样式/底图/审计日志)
6. **数据格式支持**: S-57/GeoJSON/Shapefile/GeoTIFF、文件大小限制、S-57更新链规则
7. **API 参考**: 认证API、公开API、管理API、演示数据API、健康检查、请求示例
8. **常见问题**: 登录/数据导入/地图显示/项目管理/性能/安全合规 FAQ
9. **附录**: 坐标系、S-57对象类对照表、数据库表结构、错误代码、快捷键、环境变量参考

---

## 会话 #4 — 修复项目创建 422 错误，添加表单校验

**日期**: 2026-07-21
**目标**: 诊断项目管理创建项目时的 422 错误，添加客户端表单校验

### 任务计划 (TODO)

| # | 任务 | 状态 |
|---|------|------|
| 1 | 分析 422 错误原因 | ✅ 完成 |
| 2 | 确认是否与批量导入相关 | ✅ 完成 |
| 3 | 添加前端表单校验 | ✅ 完成 |
| 4 | 提交推送 + 更新文档 | ✅ 完成 |

### 修改记录

| 时间 | 文件 | 操作 | 说明 |
|------|------|------|------|
| 2026-07-21 | `frontend/src/views/admin/ProjectManagementView.vue` | 修改 | 添加 el-form 校验: code (正则+长度), name (必填+长度), description (长度), defaultCrs (必填); 对话框关闭时自动重置 |
| 2026-07-21 | `.gitignore` | 修改 | 添加 `北极海图/` 目录 (S-57 数据文件不应提交到仓库) |

### 问题诊断

**422 错误原因**: 项目创建表单没有任何客户端校验，用户输入不符合 `ProjectCreate` Pydantic Schema 的数据直接提交到后端。

`ProjectCreate` 验证规则：
- `code`: `^[a-z0-9][a-z0-9_-]*$`, 2-80字符 → 大写字母、中文、特殊字符均不合法
- `name`: `min_length=1`, `max_length=180` → 空值不合法
- `description`: `max_length=4000`
- `default_crs`: `^EPSG:\d+$`

**与批量导入的关系**: 无关。422 是请求验证层面的错误，批量导入在 Worker 进程中操作不同的数据库表（datasets/dataset_versions/layers/import_jobs vs projects）。

### 解决方案

在 `ProjectManagementView.vue` 中添加 Element Plus 表单校验:
- 使用 `FormInstance` + `FormRules` 在提交前验证
- 校验规则与后端 Schema 保持一致
- 校验失败时阻止请求发出，在 UI 层直接提示用户
- 对话框关闭时自动清理校验状态

---

## 会话 #5 — 批量导入性能优化 + 暂停/取消功能

**日期**: 2026-07-22
**目标**: 解决批量导入188个S-57单元耗时10小时+的性能问题，并新增暂停/取消功能

### 任务计划 (TODO)

| # | 任务 | 状态 |
|---|------|------|
| 1 | 分析批量导入全链路数据流，定位性能瓶颈 | ✅ 完成 |
| 2 | 优化 `_import_vector_layers`: 单次ogr2ogr替代每图层子进程 | ✅ 完成 |
| 3 | 优化 GeoServer 发布: 预设 BBox 跳过全表扫描 | ✅ 完成 |
| 4 | 并行 Cell 处理 (ThreadPoolExecutor) | ✅ 完成 |
| 5 | 新增暂停/取消/恢复 API 端点 | ✅ 完成 |
| 6 | Worker 暂停/取消感知 + 防误杀 stale 检测 | ✅ 完成 |
| 7 | 前端暂停/取消按钮 | ✅ 完成 |
| 8 | 修复测试用例以适配并行处理 | ✅ 完成 |
| 9 | 更新文档 | ✅ 完成 |

### 性能瓶颈分析

**三大瓶颈**（详见分析报告）:
1. **每图层独立 ogr2ogr 子进程**: 188 cells × 40 图层 ≈ 7,520 次子进程调用，每次重新打开文件+新建PG连接 → 2-10小时
2. **每图层独立 GeoServer REST 发布**: 同数量级的 HTTP 调用，每次GeoServer全表扫描计算BBox → 4-10小时
3. **Cell 串行处理**: 无法利用多核CPU

### 修改记录

| 时间 | 文件 | 操作 | 说明 |
|------|------|------|------|
| 2026-07-22 | `backend/app/models.py` | 修改 | JobStatus 枚举新增 PAUSED = "paused" |
| 2026-07-22 | `backend/app/services/importer.py` | 重写 | `_import_vector_layers`: 临时schema单次ogr2ogr + ALTER TABLE RENAME替代每图层子进程; 新增 `_check_cancelled` 取消感知; publish阶段使用批量发布 |
| 2026-07-22 | `backend/app/services/geoserver.py` | 修改 | `publish_feature_type`: 预设 nativeBoundingBox 跳过GeoServer全表扫描; 新增 `publish_feature_types_batch` 批量发布方法 |
| 2026-07-22 | `backend/app/services/s57_batch.py` | 重写 | `process`: ThreadPoolExecutor并行Cell处理; `_process_cell_worker`: 独立Session线程安全处理; `_finalize_batch`: 独立Session隔离; 暂停/取消检测; batch_parallel_workers可配置 |
| 2026-07-22 | `backend/app/api/datasets.py` | 新增 | pause/resume/cancel 三个API端点 |
| 2026-07-22 | `backend/app/core/config.py` | 修改 | 新增 `batch_parallel_workers` 配置项 (默认8) |
| 2026-07-22 | `frontend/src/views/admin/BatchImportView.vue` | 修改 | 新增暂停/继续/取消按钮，动态显示 |
| 2026-07-22 | `backend/tests/test_s57_batch.py` | 修改 | FakeImportProcessor适配并行处理; create_batch返回session factory; batch_parallel_workers=1 |

### 关键决策

1. **临时 Schema 方案**: 用 `CREATE SCHEMA _imp_{id}` → 单次ogr2ogr → ALTER TABLE SET SCHEMA + RENAME → DROP SCHEMA 模式替代每图层子进程，单Cell的ogr2ogr调用从40次降到1次
2. **ThreadPoolExecutor 而非 ProcessPoolExecutor**: Cell处理是I/O密集型（ogr2ogr子进程+GeoServer HTTP），线程池足够且避免了跨进程session factory问题
3. **暂停语义**: 暂停时完成当前正在运行的Cell，不再启动新Cell。未处理的QUEUED items保留。恢复时将batch.status重置为QUEUED，worker重新拾取
4. **取消语义**: 取消时立即中断，所有QUEUED/RUNNING items标记为CANCELLED
5. **Session隔离**: 主线程和worker线程使用不同DB session（通过session factory），避免SQLite SERIALIZABLE隔离级别导致的数据不可见问题

---

## 会话 #6 — 项目配置"批量选取"数据集功能

**日期**: 2026-07-22
**目标**: 在项目管理→配置数据集对话框中，增设批量选取/取消数据集的功能

### 任务计划 (TODO)

| # | 任务 | 状态 |
|---|------|------|
| 1 | 后端新增 `GET /admin/datasets/available-ids` 轻量端点 | ✅ 完成 |
| 2 | 后端 `GET /admin/projects/{id}/dataset-layers` 新增 search 参数 | ✅ 完成 |
| 3 | 前端新增搜索框 + 批量选取按钮 | ✅ 完成 |
| 4 | 测试 + 文档更新 | ✅ 完成 |

### 修改记录

| 时间 | 文件 | 操作 | 说明 |
|------|------|------|------|
| 2026-07-22 | `backend/app/api/datasets.py` | 新增 | `GET /admin/datasets/available-ids` — 返回所有可用数据集的轻量级 ID 列表 |
| 2026-07-22 | `backend/app/api/projects.py` | 修改 | `get_project_dataset_layers` 新增 `search` 查询参数；新增 `or_` 导入 |
| 2026-07-22 | `frontend/src/views/admin/ProjectManagementView.vue` | 修改 | 新增搜索框、全选本页/取消本页/全选全部/取消全部四个批量操作按钮 |

### 关键决策
- "全选全部"通过新端点一次性获取所有匹配数据集 ID，写入 datasetDrafts Map 实现跨页跟踪
- 搜索框与后端联动，输入时自动重新加载第一页

---

## 会话 #7 — 修复图层属性加载失败 + 地图性能优化

**日期**: 2026-07-23
**目标**: 修复S-57图层属性(DSID等)查询失败问题，优化地图瓦片加载性能与状态指示灯闪烁

### 任务计划 (TODO)

| # | 任务 | 状态 |
|---|------|------|
| 1 | 分析图层属性加载失败根因 | ✅ 完成 |
| 2 | 修复 `column_reference()` 强制小写导致SQL不匹配 | ✅ 完成 |
| 3 | ogr2ogr 添加 LAUNDER=YES + allowed_fields小写化 | ✅ 完成 |
| 4 | 图层搜索添加200ms防抖 | ✅ 完成 |
| 5 | 瓦片加载状态稳定化(300ms延迟+定时器管理) | ✅ 完成 |
| 6 | 属性表查询/要素识别添加AbortController | ✅ 完成 |
| 7 | 测试 + 文档更新 | ✅ 完成 |

### 问题诊断

**问题1 — DSID等图层属性加载失败**:
`column_reference()` 在 `backend/app/api/layers.py` 中强制小写字段名(`field.lower()`)，但GDAL ogr2ogr导入S-57数据时(LAUNDER默认=NO)保留原始大写列名("DSID", "LNAM"等)。生成的SQL `"dsid"` 与PostgreSQL实际列 `"DSID"` 不匹配，导致所有大写S-57字段查询失败。

**问题2 — 地图性能退化与状态闪烁**:
- 瓦片加载事件(`tileloadstart`/`tileloadend`)直接变更 `loadState`，无任何防抖/稳定化，每次平移/缩放导致所有可见图层的状态指示灯在黄绿间快速闪烁
- `layerSearch` 无防抖，每次按键触发 `filteredGroups` 重建
- 属性表查询和要素识别无请求取消机制，过时响应会覆盖新结果

### 修改记录

| 时间 | 文件 | 操作 | 说明 |
|------|------|------|------|
| 2026-07-23 | `backend/app/api/layers.py` | 修改 | `column_reference()` 移除 `.lower()`，保留字段名原始大小写，匹配PostgreSQL实际列名 |
| 2026-07-23 | `backend/app/services/importer.py` | 修改 | ogr2ogr命令添加 `-lco LAUNDER=YES`；`allowed_fields` 存储时小写化 |
| 2026-07-23 | `frontend/src/views/MapWorkspaceView.vue` | 修改 | layerSearch添加200ms防抖(watch+lazyValue)；瓦片loadState添加300ms延迟+定时器清理；searchAttributeRows和identify添加AbortController取消机制 |

### 关键决策
- `column_reference()` 移除小写后新旧数据兼容：旧数据(allowed_fields大写+PostgreSQL列大写)→匹配；新数据(LAUNDER=YES+allowed_fields小写)→匹配
- 瓦片加载延迟300ms：快速加载的瓦片不触发黄色状态，仅持续加载超过300ms才显示loading
- AbortController取消前一个请求后再发新请求，避免并发响应的竞态条件

### 补充修复 (同日)

**问题发现**: 修复上线后 DSID 和 C_ASSO 图层仍然"加载失败"且属性表报错。

**根因**: S-57 的 DSID(数据集元数据) 和 C_ASSO(要素关联) 是非空间图层，`ogrinfo` 报告 `geometryType` 为 null，`ogr2ogr` 创建的表**没有 `geom` 列**。后端 SQL 硬编码 `ST_Transform(geom,4326)` 导致 "column geom does not exist"；GeoServer 发布无空间列的表后 WMS 瓦片请求失败。

**补充修改**:

| 时间 | 文件 | 操作 | 说明 |
|------|------|------|------|
| 2026-07-23 | `backend/app/api/layers.py` | 修改 | 新增 `_layer_has_geometry()` 辅助函数；`search_features`/`export_features` 对非空间图层使用 `NULL AS geometry`；`identify_feature` 对非空间图层返回 400 |
| 2026-07-23 | `backend/app/services/importer.py` | 修改 | GeoServer 发布前过滤掉非空间图层(geometry_type 为 unknown/none/空)，仅发布有几何列的表 |
| 2026-07-23 | `backend/app/schemas.py` | 修改 | `MapLayerConfig` 新增 `geometry_type` 字段 |
| 2026-07-23 | `backend/app/api/projects.py` | 修改 | 返回 `MapLayerConfig` 时传递 `geometry_type` |
| 2026-07-23 | `frontend/src/types/index.ts` | 修改 | `MapLayerConfig` 新增 `geometryType` 字段 |
| 2026-07-23 | `frontend/src/views/MapWorkspaceView.vue` | 修改 | 新增 `isNonSpatial()` 判断；非空间图层跳过 WMS 瓦片加载并显示"属性表"标签 |

---

## 会话 #8 — 建立后端 S-57 图层分类事实来源

**日期**: 2026-07-26
**目标**: 为后续导入分类元数据和图层解析 API 建立纯函数、不可变的后端统一分类目录

### 任务计划 (TODO)

| # | 任务 | 状态 |
|---|------|------|
| 1 | 先写精确集合、分类行为、几何判断和不可变性测试 | ✅ 完成 |
| 2 | 运行目标测试，确认因分类模块缺失进入 RED | ✅ 完成 |
| 3 | 实现最小 S-57 分类目录并保持无外部依赖 | ✅ 完成 |
| 4 | 运行目标 pytest 与 ruff，确认 GREEN | ✅ 完成 |
| 5 | 更新 living docs 并自审变更范围 | ✅ 完成 |

### 修改记录

| 时间 | 文件 | 操作 | 说明 |
|------|------|------|------|
| 2026-07-26 | `backend/tests/test_s57_layer_catalog.py` | 新建 | 精确锁定五组已知对象集合，并覆盖分类、推荐、渲染、排序、几何与不可变性 |
| 2026-07-26 | `backend/app/services/s57_layer_catalog.py` | 新建 | 提供 `S57LayerRule`、代码规范化、保守几何判断和统一分类纯函数 |
| 2026-07-26 | `docs/09-system-architecture.md` | 修改 | 记录分类服务边界、稳定档案/分类及依赖约束 |
| 2026-07-26 | `docs/10-work-log.md` | 修改 | 记录 TDD 过程、测试结果与关键决策 |
| 2026-07-26 | `docs/11-work-summary.md` | 修改 | 汇总本阶段成果与后续使用边界 |

### TDD 证据

- **RED**: `F:/polar-gis/.venv/Scripts/python.exe -m pytest tests/test_s57_layer_catalog.py -v` → 收集阶段按预期失败，`ModuleNotFoundError: No module named 'app.services.s57_layer_catalog'`
- **GREEN**: 同一 pytest 命令 → `8 passed, 1 warning`
- **Lint**: `F:/polar-gis/.venv/Scripts/python.exe -m ruff check app/services/s57_layer_catalog.py tests/test_s57_layer_catalog.py` → `All checks passed!`

### 关键决策

1. 分类目录仅使用标准库，不访问数据库、Web 框架、GDAL 或 GeoServer，方便导入流程和 API 后续共同复用。
2. 已知对象始终保留其固定 `load_profile`；`recommended` 仅由核心/航行档案与 `style_mapped=True` 共同决定。
3. 未知有几何对象进入 `optional_other`，未知 `M_` 有几何对象进入 `metadata_quality`，未知无几何对象进入 `non_spatial`。
4. 几何判断只排除明确无几何值，避免将 `GeometryCollection` 等合法类型错误归为非空间。
5. 所有分类结果 `default_visible=False`，不改变现有地图懒加载行为。

### 审查修复（2026-07-26）

- **RED**: 更新测试以直接导入生产五组集合、与独立规格集合精确比较并对生产集合执行两两互斥；同时要求核心集合由完整规则表键派生。运行目标 pytest 得到 `1 failed, 7 passed`，失败点为缺少 `_CORE_CHART_RULES`。
- **GREEN**: 将核心成员与展示元数据统一到 `_CORE_CHART_RULES`，从其键派生公开 `CORE_CHART`，并删除无消费者 `_RESTRICTION_HARBOR`；目标 pytest 恢复为 `8 passed, 1 warning`。
- **Lint**: 目标 ruff 输出 `All checks passed!`。
- **测试简化**: 每组期望集合只保留一份，删除本地集合自我等值断言、重复逐成员计数及对私有规则表名称的实现耦合；最终测试仅锁定公开集合与分类行为。
- **文档维护**: 将架构目录中的固定”40个测试”改为不易过期的”按业务模块组织”。

---

## 会话 #9 — S-57 海图图层批量加载与智能筛选

**日期**: 2026-07-26
**目标**: 在保留现有数据集级懒加载机制下，实现 S-57 数据集批量解析、智能筛选、分批加载、取消和精确卸载

### 任务计划 (TODO)

| # | 任务 | 状态 |
|---|------|------|
| 1 | 验证已完成分类目录 | ✅ 完成 |
| 2 | 导入 metadata 合并 + 非空间过滤 | ✅ 完成 |
| 3 | 项目级批量图层 resolve API | ✅ 完成 |
| 4 | 前端类型、API 客户端、批量纯逻辑 | ✅ 完成 |
| 5 | MapWorkspaceView 批量加载 UI | ✅ 完成 |
| 6 | S-57 更新链校验增强 | ✅ 完成 |
| 7 | 文档更新与最终交付 | ✅ 完成 |

### 修改记录

| 时间 | 文件 | 操作 | 说明 |
|------|------|------|------|
| 2026-07-26 | `backend/app/services/importer.py` | 修改 | 新增 `merge_s57_layer_metadata()`；S-57 导入合并分类快照 |
| 2026-07-26 | `backend/app/schemas.py` | 修改 | 新增批量解析 Schema；`MapDatasetConfig` 增加 `dataType` |
| 2026-07-26 | `backend/app/api/projects.py` | 修改 | 新增 `POST /map-layers/resolve` 端点 |
| 2026-07-26 | `backend/app/services/s57_batch.py` | 修改 | 新增 `S57ChainValidationError`；区分 base missing vs update gap |
| 2026-07-26 | `backend/app/api/datasets.py` | 修改 | 批次详情填充 `details.missingUpdates` |
| 2026-07-26 | `backend/tests/test_importer.py` | 新建 | S-57 metadata 合并测试 (7 tests) |
| 2026-07-26 | `frontend/src/types/index.ts` | 修改 | 新增批量解析和进度类型 |
| 2026-07-26 | `frontend/src/api/projects.ts` | 新建 | API 客户端封装 |
| 2026-07-26 | `frontend/src/api/projects.test.ts` | 新建 | API 测试 (3 tests) |
| 2026-07-26 | `frontend/src/utils/mapLayerBatch.ts` | 新建 | 批量常量与纯函数 |
| 2026-07-26 | `frontend/src/utils/mapLayerBatch.test.ts` | 新建 | 批量逻辑测试 (12 tests) |
| 2026-07-26 | `frontend/src/views/MapWorkspaceView.vue` | 修改 | 批量选择/加载/取消/卸载完整实现 |
| 2026-07-26 | `frontend/src/styles.css` | 修改 | 批量工具栏紧凑样式 |
| 2026-07-26 | `docs/*` | 修改 | 更新 02/04/05/09/10/11/12 |

### 验证结果

- **后端**: 61 tests passed, ruff clean
- **前端**: 22 tests passed, vue-tsc clean, vite build 成功
- **无数据库迁移**: 所有新增字段使用已有 JSONB 列

### 关键决策

1. 批量加载复用现有 attachWmsLayer/detachWmsLayer，不创建第二套 WMS 实现
2. 分类事实来源仅在后端维护；前端不复制业务规则
3. 旧数据无 metadata.s57 时动态分类回退，不强制迁移
4. 不可变 Set/Map 替换确保 Vue 3 响应式正确触发
5. 项目无 Playwright 基础，端到端验收留待手工阶段

---

## 会话 #10 — 一键导入全球海图底图

**日期**: 2026-07-27
**目标**: 在现有S-57批量导入功能之上，增加一键导入全球海图概览底图

### 新增文件
- `backend/app/resources/s57_basemap_profiles/global_overview_v1.json` — 18 Cell profile
- `backend/app/services/s57_basemap.py` — 预检 + 后处理服务 (~320行)
- `backend/app/api/s57_basemaps.py` — 管理员 API (profiles/preflight/import/runs)
- `backend/migrations/versions/0004_add_purpose_metadata_to_s57_batches.py` — 迁移
- `backend/tests/test_s57_basemap.py` — 19 测试
- `backend/tests/test_s57_basemap_api.py` — 7 测试
- `北极海图_文件清单.txt` — 1188 文件清单

### 修改文件
- `backend/app/models.py` — S57ImportBatch 新增 purpose + metadata_json
- `backend/app/schemas.py` — 扩展 schema
- `backend/app/core/config.py` — 新增 basemap 配置
- `backend/app/main.py` — 注册路由
- `backend/app/services/geoserver.py` — Layer Group / GWC 方法
- `backend/app/services/s57_batch.py` — basemap 后处理钩子
- `frontend/src/views/admin/BatchImportView.vue` — 底图功能区
- `frontend/src/types/index.ts` — 新类型
- `deploy/.env.example` — 配置项

### 测试结果
- 全部 87 个测试通过 (61 现有 + 26 新增)
- 预检服务 19 测试覆盖 profile 加载、DSID 提取、更新链校验、文件计数
- API 7 测试覆盖访问控制和空源预检

---

## 会话 #11 — 海图批量加载性能优化（阶段一至四）

**日期**: 2026-07-28
**目标**: 解决批量加载S-57海图后浏览器卡顿、瓦片空白、交互响应慢等问题

### 根因分析

1. **无视口裁剪** — 所有已加载图层的 TileWMS 源在每次平移/缩放时同时请求瓦片，40+ 图层产生 320-640 并发请求，超过浏览器 6 连接/源限制
2. **无比例尺过滤** — 高密度图层 (SOUNDG/LIGHTS/BOY*/BCN*) 在所有缩放级别请求瓦片，产生大量几乎透明的瓦片
3. **无并发控制** — 所有图层同时发起瓦片请求，导致队头阻塞和超时级联
4. **业务图层未使用 GWC** — 直接访问 GeoServer WMS，每次平移/缩放重新渲染
5. **GeoServer 硬编码全球范围** — `publish_feature_type()` bbox 为 (-180,-90,180,90)，北极数据扫描范围远大于实际
6. **SLD 无比例尺规则** — 10 个样式预设无 MinScaleDenominator/MaxScaleDenominator
7. **无空间索引** — `importer.py` 未创建 GIST 索引和 ANALYZE
8. **Nginx 无优化** — 无 HTTP/2、gzip、upstream keepalive、缓存头
9. **GeoServer 无 JVM 调优** — compose.yml 无 JAVA_OPTS
10. **投影切换全量重建** — `switchProjection()` 先全部销毁再全部重建

### 第一阶段 — 性能诊断（不改渲染行为）

#### 新增文件
- `frontend/src/utils/mapRenderScheduler.ts` — 纯函数渲染调度器 (~350行)
- `frontend/src/utils/mapRenderScheduler.test.ts` — 32 个单元测试

#### 修改文件
| 文件 | 变更 |
|------|------|
| `frontend/src/types/index.ts` | 新增 MapTilePerformanceStats、ChartRenderMode 类型；BulkResolvedLayer 扩展 8 个可选 GWC/scale 字段 |
| `frontend/src/utils/mapLayerBatch.ts` | 新增 SMART_* 配置常量 (10个)；新增 PerLayerStatsManager 类 |
| `frontend/src/views/MapWorkspaceView.vue` | 接入瓦片加载耗时统计 (tileloadstart/end/error)；map-status 增加性能展示+可折叠调试面板 |
| `deploy/nginx/default.conf` | 增加 perf 日志格式 ($request_time/$upstream_response_time)；gzip；upstream keepalive；缓存头穿透 |
| `frontend/src/styles.css` | 性能统计样式、图层状态文字样式、batch-mode-row |

### 第二阶段 — 视口裁剪 + 比例尺 + RenderPlan 纯函数

- 实现 `buildRenderPlan()` 核心调度算法，输出 activate/attach/suspend/detach/warming 五类操作
- `isLayerInViewport()`: extent→当前投影转换 + 20% buffer + intersects 判断；null extent 保守放行
- `isLayerInScaleRange()`: 显式 zoom/minScaleDenom → 回退 DEFAULT_SCALE_HINTS (30+ S-57 对象类)
- `sortRenderCandidates()`: 手动强制优先 → displayPriority ASC → objectClass → id
- DEFAULT_SCALE_HINTS 集中维护：SOUNDG minScale=25000，导航标志 minScale=50000，危险物 minScale=100000 等
- resolutionToScaleDenom/scaleDenomToResolution 转换函数
- 32 个单元测试覆盖：视口裁剪/比例尺过滤/warming 预算/活动预算/LRU/模式语义/边界情况

### 第三阶段 — 状态分离 + reconcileRenderPlan + 智能模式调度

- 单 `loadedLayerIds` 拆分为 7 个状态集：selectedLayerIds / attachedLayerIds / activeLayerIds / warmingLayerIds / suspendedLayerIds / manuallyForcedLayerIds / failedLayerIds
- `toggleLayer()` 控制 selectedLayerIds，scheduler 决定何时 attach/activate
- `attachWmsLayer`/`detachWmsLayer` 同步更新所有状态集
- `reconcileRenderPlan()`: moveend 150ms 防抖调用 buildRenderPlan → 执行 plan
- `runLruEviction()`: 30s 后清理非选中/非强制休眠图层（保护底图/WMTS/AIS/气象/测量/属性表）
- 批量工具栏增加模式切换、活动/休眠/等待统计、清理休眠按钮
- 图层行增加状态文字（已显示/加载中/视口外休眠/等待加载/加载失败）
- `switchProjection()` 使用 renderGeneration + reconcileRenderPlan

### 第四阶段 — 后端 GWC 传输提示 + 比例尺提示

| 文件 | 变更 |
|------|------|
| `backend/app/schemas.py` | BulkResolvedLayer 新增 render_transport/tile_service_url/grid_set/cacheable/min_scale_denominator/max_scale_denominator/render_cost |
| `backend/app/services/s57_layer_catalog.py` | S57LayerRule 新增 4 个 scale 字段；新增 `_SCALE_RULES` 字典 (30+ 对象类)；classify_s57_layer() 应用 scale hints |
| `backend/app/api/projects.py` | `_build_resolved_layer()` 计算 GWC cacheable → render_transport=gwc_wms/wms；返回 tile_service_url + scale hints |

### 部署修复

- `backend/Dockerfile` & `frontend/Dockerfile`: 配置阿里云 PyPI/npm 镜像，pip timeout 120s
- `deploy/compose.yml`: S-57 底图卷挂载从绝对路径 `/data/s57-basemaps` 改为相对路径 `../data/s57-basemaps`
- `deploy/nginx/default.conf`: HTTP/2 支持完成

### 测试结果

- 后端 87 个测试全部通过
- 前端 59 个测试全部通过 (27 已有 + 32 新增)
- TypeScript vue-tsc 零错误
- Python pytest 零错误

### 关键决策

1. 状态分离：selected ≠ attached ≠ active ≠ warming ≠ suspended，各司其职
2. 纯函数调度：buildRenderPlan 无副作用，仅依赖 extent/proj 工具
3. 比例尺规则单源：DEFAULT_SCALE_HINTS (前端) 与 _SCALE_RULES (后端) 保持同步
4. standard 模式 = 完全向后兼容，一键回退
5. LRU 保护清单：底图/WMTS/AIS/气象/测量/选择高亮/编辑图层/属性查询图层 永不驱逐
6. 新增 API 字段全部可选，旧客户端不受影响

---

## 会话 #28 — PolarOptionNav-System-V3 导航集成 / 批次 A：审计、契约、基线（2026-10-29）

### 目标

在不替换 Polar-GIS 现有 S-57、海冰、手绘航路、认证与五服务部署的前提下，为环境感知、
船舶性能、风险评价与多目标规划建立独立业务域；先完成仓库审计、契约、配置与测试基线。

### 实际基线

- Polar-GIS `master` HEAD：`728020b2bccbfed148bdeefe50fae43fcd564f08`；V3 `main` HEAD：`237767b122ba52ff612411d15984b23a2d2a6495`（嵌套仓库，工作区 clean）。
- 后端：`pytest tests/ -q` → **214 passed, 0 failed**（72+72+70），仅有 Starlette/httpx 与 NumPy 2.5 deprecation warnings。
- 前端：`npm test` → **20 files / 353 tests passed**（Vitest 3.2.7/jsdom，38.6s）。
- `ruff check app tests` → **29 errors（24 fixable）**，均为既有文件问题；本任务新增代码单独检查通过。

### 完成内容

1. 审计报告 `docs/plans/v3-integration-audit.md`：两项目技术栈、六类功能分类、重叠清单、
   V3 可复用/需重构/不迁移文件、环境/地图/航路冲突、缺失数据、差距矩阵、文档与代码不一致。
2. `.gitignore` 加入 `PolarOptionNav-System-V3/`（嵌套参考仓库不得提交）与导航测试临时目录。
3. 新建 `backend/app/navigation/`：
   - `contracts/{coordinates,directions,time,units,quality,evidence,status}.py`，含
     `TimeMatchInfo`、`DataQuality`、`combine_quality`、`within_max_lag` 等扩展；
   - `resources/vessels/xuelong2.json`（V3 原样复制，1,996B）；
   - `resources/grids/northeast_passage_25km_static.npz`（488,119B）；
   - `resources/risk/weights_v1.json`（从 V3 `environment_model.py:26-90` 常量生成，记录
     legacy_v1 权重/公式与 real_v1 缺测策略）。
4. `backend/app/core/config.py` 新增 `NAVIGATION_*`/`PLANNER_*` 设置与
   `resolved_navigation_ice_data_root`/`resolved_navigation_manifest_path`。
5. `backend/tests/conftest.py` 注入临时 `NAVIGATION_DATA_ROOT`/`NAVIGATION_ICE_DATA_ROOT`/
   `PLANNER_RESULT_ROOT`，避免测试读取开发机数据或写仓库。
6. 新增 `backend/tests/test_navigation_contracts.py`（10 tests）：单位、方位、FROM/TO、
   UTC/naive 拒绝、TimeMatch 三值、max-lag、质量合并、FeasibilityStatus 禁止布尔化、WGS84 边界。

### 决策

- 依赖不新增：现有 netCDF4/numpy/Pillow/pyproj 足够；V3 `core/providers/*` 的 netCDF4 readers
  优先复用，xarray/rasterio 仅在读取不可拆分时评估。
- 风险模型保留 `legacy_v1` 原权重/公式用于 `allow_synthetic_research`；新增 `real_v1`
  禁止合成、雾缺失为 null、冰/深度缺失为 UNKNOWN，规划要求五类环境字段齐全。
- 合成数据必须经 manifest 标记 `quality=synthetic`，`real_only` 拒绝；避免把测试文件伪装成 real。
- 本批次不新增 API/迁移/前端可见功能；后续 B-E 按计划推进。

### 下一批依赖

- Batch B 需要：Provider 接口（含 `sample_many`/manifest/time match）、IceService 适配、
  水深瓦片、船舶模型/UKC、前端环境图层骨架。
- 需要保留的约束：单一 OpenLayers Map、唯一 singleclick/pointermove、手绘航路 localStorage v1
  key 不变、S-57 瓦片队列/缓存不被打断。

---

## 会话 #28 — 批次 B：环境感知与船舶模型（2026-10-29）

### 完成内容

**后端**
- `backend/app/navigation/environment/`：models（ProviderSample/FieldObservation/Source/Snapshot）、
  manifest（synthetic 标记）、time_manager（latest_not_after/issue≤requested/max-lag/nearest）、
  service（五字段故障隔离、查询/批量/矢量场/快照）。
- `providers/`：GEBCO（深度/陆地/PNG 瓦片）、Ice（IceService 适配 + neXtSIM 后端，浓度/厚度分开）、
  CARRA2（si10/wdir10 或 u10/v10）、TOPAZ5（原生 x/y + 地理 EN 旋转）、WAM（VHM0/VTPK/VMDR）。
- API：`/api/v1/navigation/environment/{sources,times,query,batch-query,field,tiles}`（JSON 鉴权，
  瓦片公开）；`/api/v1/navigation/vessels`（静态资料 + depth-safety）。
- 雪龙2：draft 7.85m、UKC 2.0m、required 9.85m、15MW、18kn；厚度缺失只标该分量 missing。

**前端**
- `types/navigation.ts`、`api/navigation.ts`。
- `useEnvironmentOverlays.ts`：唯一 Map attach/dispose/reload；水深 XYZ（共享 LRU/队列/generation abort）；
  风/流/浪矢量（moveend 300ms 防抖、旧请求 abort、最多 600 点）；独立 layer state；后端 point query hover。
- `utils/mapEnvironment.ts`：地理方位角→WGS84 端点→投影（避免 3413 平面 u/v 误用）；箭头/颜色/bbox/格式化。
- 组件：`EnvironmentLayerPanel`、`EnvironmentTimeControl`、`EnvironmentValueTooltip`、`VesselProfilePanel`。
- `MapWorkspaceView.vue`：环境叠加菜单 7 项、左侧环境面板、唯一 pointermove/singleclick 扩展、moveend/
  投影切换/卸载生命周期；zIndex 50/64/66/68。

### 测试

- 后端：`pytest tests/ -q` → **246 passed**（新增契约 10、Provider/Service 10、环境 API 8、船舶 API 4），
  无失败；新增文件 `ruff` 通过。
- 前端：`npm test` → **23 files / 365 tests passed**；`npm run typecheck` 零错误。
- 新增测试覆盖：合成 manifest 下 `real_only` 拒绝、`allow_synthetic_research` 接受、缺文件故障隔离、
  TOPAZ 旋转、WAM FROM、CARRA2 FROM/u/v、冰浓度 0 有效/厚度缺失、GEBCO 陆地/越界、双投影箭头、
  bbox 反经线、环境面板/船舶面板源码不变量。

### 决策与限制

- 环境显示默认 `allow_synthetic_research` 并逐层显示 quality；规划阶段仍默认 `real_only`，两种策略分离。
- 未修改 `IceService`/`IceTimeline`/手绘航路/S-57 调度；海冰时间轴仍是冰情唯一底部时间控件。
- 无真实 GEBCO/neXtSIM/CARRA2/TOPAZ5/WAM 数据，E2E 只能用 `navigation_manifest.json` 标记的合成数据。
- 风险栅格、规划图层、采纳/编辑/重评留到 C/D 批次。

---

## 会话 #28 — 批次 C：风险、规划算法、异步任务与持久化（2026-10-29）

### 完成内容

- 风险：`risk/evaluator.py` 精确移植 V3 `legacy_v1`（权重/冰/深度/风/浪/雾公式），新增
  `real_v1`（缺测≠0；雾 null；冰/深度缺失→UNKNOWN/阻断；权重按可用分量归一）；
  `weights_v1.json` 作为版本化参数源。
- 规划：静态 NPZ 网格 loader（无 rasterio）、环境适配器（real_only/allow_synthetic_research）、
  统一 `EdgeTransitResult`（船舶参数注入：max speed/power/UKC/冰能力）、D* Lite（三目标种子）、
  自研 NSGA-III（Risk/Energy/Time，Distance 仅统计）、PlannerService（plan/risk_only/evaluate_route）。
- 持久化：`planning_runs`/`planning_routes` 模型 + Alembic `0005_navigation_planning`；
  风险栅格 gzip 文件原子写；0004 迁移增幂等保护以支持 fresh DB。
- Worker：`run_once(session_factory)`、`claim_planning_run`、10 分钟心跳超时、短事务心跳/
  取消新会话读取/worker_id fencing；规划异常只标 failed，不杀唯一 worker。
- API：`/navigation/plans` 创建/列表/详情/候选/取消/风险格/单格/重评；
  `/navigation/risk/evaluate` 区域风险（risk_only）；错误码细分。

### 测试

- 后端全套 **277 passed**（新增 31：风险 9、网格/适配 4、D*/NSGA/能耗 6、规划服务 3、
  Worker 3、规划 API 6）。
- Alembic：全新 SQLite `upgrade head` 通过；模拟“0004 后无 planning 表”再升级 0005 通过。
- `ruff` 新增代码通过；既有 29 个历史 lint 未动。

### 决策

- `real_only` 是规划默认；`allow_synthetic_research` 必须显式选择，合成逐格标 quality，UI D 批次提示。
- `NO_FEASIBLE_ROUTE` 仍写风险栅格，状态 failed 但风险分析可用。
- `evaluate_route` 只读 run 风险快照（不重新请求 Provider），≤5km 加密并逐格检查；跨陆地/浅水/
  缺测格返回 blockedCellId/reason。
- v1 Worker 串行、规划优先级低于导入；文档说明后续可拆独立 planner worker。

### 下一批依赖

- D 批次需要：planning API 客户端、候选航线/风险栅格图层、规划面板/对比/采纳/编辑/stale、
  唯一 pointermove/singleclick 扩展、localStorage v1→v2 兼容。C 已提供全部后端契约。

---

## 会话 #28 — 批次 D：前端规划工作台与航路融合（2026-10-29）

### 完成内容

- `stores/navigation.ts`：任务列表/当前 run/候选/选中/风险格/单格/选点模式/风险识别；
  2s 轮询与 completed 自动拉候选；取消；`adoptRoute`；`refreshAdoptedMetrics`（按 snapshot.planId 重评）。
- `api/navigation.ts` + `types/navigation.ts`：规划/风险/重评契约；`RouteDraft` 增 adopted 来源与
  `planningSnapshot`。
- 图层：`usePlanningRouteLayer`（zIndex 90，候选/推荐/选中样式，fit/pick/projection reload/dispose）；
  `useRiskGridLayer`（zIndex 70，WGS84 GeoJSON，null/unknown 独立灰色样式，cell 点选）。
- UI：`RoutePlannerPanel` 手动/智能切换；`IntelligentPlanningPanel` 任务/船舶/对比/风险/结果；
  `NavigationTaskPanel`、`RouteComparisonPanel`（ECharts Pareto + 采纳）、`RiskAnalysisPanel`
  （字段切换/地图点选/单格详情/区域评估）、`PlanningResultPanel`（状态/取消/历史/快照时间/合成横幅）。
- 采纳/编辑：localStorage key 仍 v1，payload v2；coerce 保留 adopted/source/snapshot；采纳后切回
  手动并 fit；修改后 stale 提示 + 重新评估按钮，旧指标不以当前值展示。
- 交互：唯一 `singleclick` 优先级扩展（pickMode→测量/手绘 guard→riskInspect→weather→identify→
  手绘航路→算法航路）；唯一 `pointermove` 不新增；pickMode/riskInspect 与既有工具互斥；投影切换/
  卸载/关闭面板清理。

### 测试

- 前端全套 **28 files / 385 tests passed**；`vue-tsc` 零错误；`npm run build` 通过。
- 新增：mapEnvironment 双投影、routePlanning hash/stale、navigation store 采纳/选点/互斥、
  planning layers 生命周期、planning panels 契约、MapWorkspace 单 Map/单 handler/图层 attach/
  projection reload、v1 payload 从旧 key 加载。
- 既有 365 tests 全部保留通过。

### 决策与限制

- 未改动 `useRouteDrawing`/`routesStore` 的手动绘制/拖拽行为；规划航路独立图层/独立 store。
- “采纳”只复制到草稿，不修改原始推荐结果；不是自动驾驶执行。
- ECharts 只在有真实候选时绘制；合成数据仍显示算法输出并带横幅。
- 尚未做 E 批次的 Docker/回归/合成 fixture/E2E；本批次无部署变更。

---

## 会话 #28 — 批次 E：部署、E2E、回归与交付（2026-10-30）

### 完成内容

- Docker：backend+worker 挂载 `/data/navigation`；worker 补 `/data/ice`；`PLANNER_RESULT_ROOT` 共享存储；
  `NAVIGATION_*`/`PLANNER_*` 环境变量；`.env.example` 同步；`data/navigation/*/README.md` 与
  `.gitignore` 白名单。
- 合成 fixture：`scripts/navigation/generate_synthetic_fixtures.py`（五字段 + synthetic manifest）；
  `e2e_synthetic.py`（API+worker+planner+risk+evaluate）；`e2e_ui_smoke.cjs`（Playwright）。
- E2E 结果：3 条候选；风险格 15,731 单元；推荐/重评 risk/energy/time 一致；real_only 负例
  `ENVIRONMENT_DATA_MISSING`；risk_only 完成；全链 17.0s，worker 10.7s；UI 链路通过。
- 最终测试：后端 277 passed；前端 385 passed；typecheck/build 通过；compose config 通过。
- 文档：docs/09/10/11/12 + `docs/plans/v3-integration-final-report.md`（21 项）。

### 未完成 / 明确限制

- 本机无真实 GEBCO/neXtSIM/CARRA2/TOPAZ5/WAM 数据；**真实环境规划未验证**，E2E 为合成研究数据。
- 未运行真实 GeoServer/GWC/S-57 批量导入与 44 项手工浏览器回归；不得宣称真实服务回归通过。
- Docker 镜像构建尝试已启动（受网络/时间限制）；compose 配置已验证，最终构建结果以实际日志为准。
- 无项目成员 ACL、无实时船位/自动操舵/路线执行；Worker 串行。

---

## 会话 #29 — 用户反馈修复：合成参数/进度/任务列表/对比度（2026-10-30）

### 问题与修复

1. **看不到/无法修改合成信息**
   - 新增 `syntheticOverrides` 请求契约与校验（仅 allow_synthetic_research，10 个字段/范围）。
   - 任务面板显示算法所需字段、说明空值由 Provider/gap-fill 自动处理，支持“从起点读取当前环境值”
     并逐项编辑；覆盖应用到全规划区，逐格标 synthetic + research-override。
   - 结果面板显示每个环境字段的 quality/source 与本次合成覆盖值。
2. **规划卡在 10%，历史任务不能编辑/删除**
   - Provider 采样改为 1000 点分块并在块间更新进度/检查取消；进度/阶段现在按
     环境采样→多目标优化→结果保存推进（API 实测 0→2→12…65→95→100）。
   - 新增 `planning_runs.title` + Alembic `0006`；`PATCH` 重命名、`DELETE` 删除终态任务
     （级联航线、删除风险栅格文件）；结果面板历史项加入重命名/删除按钮。
3. **选中计划蓝底文字看不清**
   - 智能规划抽屉改为亮色主题：深色文字/浅色卡片/浅青选中行 + 左边框；环境图层左侧暗色面板不变。

### 验证

- 后端新增 3 个测试，全套 **280 passed**；前端 385 passed；typecheck/build 通过；ruff 通过。
- 迁移 `0006` 在“0005 后无 title 列”的 SQLite 数据库升级通过。
- API 实测进度过渡；`PATCH/DELETE` 返回 200/204；Playwright UI smoke 通过，截图已更新
  （含 `windSpeedMs=13` 合成覆盖标签、浅色可读历史列表）。

### 追加修复（同一会话）

- 合成研究模式下环境查询对缺失字段执行与规划器一致的确定性 gap-fill，任务面板选择合成策略后
  自动填入实际值（不再只显示“自动”）；可清空恢复自动。
- 新增 `PLANNER_MAX_SEARCH_EXPANSIONS=200000`；D* 超限返回 `NO_FEASIBLE_ROUTE`（保留风险格），
  避免随机/极端合成值导致 `PLANNER_TIMEOUT`。
- 后端 `_as_utc` 修复 SQLite datetime 无时区导致的 API 时间偏差；前端历史列表改用本地时区
  `toLocaleString('zh-CN')`。
- S-57 `optional_other` zIndex 100→45，避免可选海图图层盖住风险格；风险页打开且任务已完成时
  自动加载 combined 风险格，`setGrid` 显式设置可见。
- 最终：后端 280 passed、前端 386 passed、typecheck/build/ruff 通过。

---

## 会话 #30 — 智能规划超时/首载空态/冰情性能（2026-10-30）

### 问题定位（证据驱动）

1. **智能规划耗时/失败**：规划网格固定 15,731 个 25km 单元。`CARRA2` 与 `WAM` 的
   `sample()` 对每个格点调用 `coverage()`，每次都要对完整坐标网格做 `nanmin/nanmax`。
   用 1200×1200 网格实测：200 个风场点从 0.065s 增至 1.339s（约 6.4ms/点）；按 15,731
   格推算风/浪两字段即需数百秒，必然触发 300s `PLANNER_TIMEOUT`。`GEBCO` 的越界分支
   同样重复计算 coverage；`IceProvider(polar_gis)` 每个格点调用 `info()` 并新建
   `Transformer`，进一步放大耗时。
2. **首次进入环境叠加无信息**：`/ice/info` 会打开目录内每个 NetCDF 做元数据扫描；导航
   `EnvironmentService` 又构造了**第二个** `IceService`，同一目录被并发扫描两遍。前端
   默认 30s 超时，冷启动超时后 `info=null`，菜单显示“无数据”，退出重进时服务端已有缓存
   才恢复。且 `loadInfo/loadSources` 原先排在默认数据集加载之后，进一步扩大空窗。
3. **冰情图层慢**：冷日期 `_grid` 需整读 26M 单元；`info()` 每次重扫；`warm_default_grid`
   每次 `/info` 都新起线程；PNG 使用 `optimize=True` 做全参数搜索。

### 修改

**后端**
- `environment/providers/carra2.py`、`wam.py`：coverage 缓存 + `sample()` 不再逐点计算。
- `environment/providers/gebco.py`：先读坐标轴判断覆盖，越界不加载 elevation；coverage 缓存；
  `_elevation_grid()` 延迟加载；PNG `compress_level=1`。
- `environment/providers/ice.py`：polar 后端缓存 `info()` 60s、复用 `Transformer`；
  `EnvironmentService` 传入与 API 相同的 cache/zoom，构造共享实例。
- `services/ice.py`：新增 `shared_ice_service()`；`info()` 结果缓存（目录变化失效）；
  `_start_warm_once()` 防止重复预热；PNG `compress_level=1`。
- `api/ice.py`：改用共享实例。
- `main.py`：FastAPI startup 后台执行冰情索引/默认网格预热，失败仅告警。
- `tasks/processor.py`：`PLANNER_TIMEOUT / ENVIRONMENT_DATA_MISSING / NO_FEASIBLE_ROUTE`
  输出中文原因与可操作建议。
- `api/navigation_plans.py`：`real_only` 起点缺测时入队前 422，字段名中文化并提示改用合成研究。

**前端**
- `MapWorkspaceView.vue`：`loadInfo/loadSources` 提前到 map-config 之后、默认数据集与
  `buildMap()` 之前；冰情菜单增加“加载中/待加载”；面板打开时失败重试；移除模拟/安全提示。
- `useIceOverlay.ts`：`infoLoaded` 状态、并发保护、attach 自动加载。
- `useEnvironmentOverlays.ts`：`sourcesLoaded` 状态、并发保护、attach 自动加载、失败保留旧数据、
  available 时清除 layer error。
- `api/ice.ts` / `api/navigation.ts`：首载超时 30s→120s。
- `utils/routePlanning.ts`：错误信息保留后端细节。
- `NavigationTaskPanel.vue`：补充网格范围与合成覆盖使用说明；“合成环境参数”去掉“仅研究验证”。
- `RouteInfoFlyout/RoutePlannerPanel/MapWorkspaceView/AdminDashboardView/AppLayout/IceLayerPanel`：
  删除合成/模拟/非认证等黄色提示与声明。

### 验证

- 后端：`pytest backend/tests` 全通过；新增 provider coverage 不重算、`/info` 缓存、共享实例
  3 个回归测试；ruff 对改动文件通过（仓库既有 39 个无关 lint 未处理）。
- 性能基准：1200×1200 风/浪等大网格、15,731 规划格，环境采样合计 19.78s（修复前同规模风场
  单字段即约 100s+）。
- 合成 E2E：3 条候选、风险格 787 features、采纳重评一致、real_only 422 负例、risk_only 完成。
- 前端：29 files / 389 tests passed；`vue-tsc` 零错误；`npm run build` 通过。

### 决策与已知限制

- 未获得真实 GEBCO/CARRA2/TOPAZ5/WAM 数据，无法在本机验证真实环境规划；性能基准使用
  格式正确的合成 NetCDF，规模按真实 1200×1200 网格模拟。
- 真实 Provider 仍为逐点 Python 采样；若数据网格显著大于 1200×1200，风场仍可能成为瓶颈，
  后续可做 Provider 级向量化 `sample_many`。
- 冰情冷日期仍会整读一次网格；已通过共享实例、单飞、预热与 info 缓存降低首载影响。

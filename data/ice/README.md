# 冰情数据目录 (Ice Overlay Data)

本目录用于存放冰情图层的 NetCDF 数据文件,由后端 `app/services/ice.py` 读取,
经 `/api/v1/ice/...` 渲染为 PNG XYZ 瓦片叠加到地图工作台。

## 文件约定

- 文件名必须以 **8 位日期**结尾,例如:

  ```text
  sic_modis-aqua_amsr2-gcom-w1_merged_nh_1000m_20220101.nc
  ```

- 时间轴只展示**实际存在的文件日期**,不会自动补齐缺失日期;
- 网格要求:**1-D `x`/`y` 坐标轴**(升序/降序均可),投影为 EPSG:3411
  (NSIDC 极射赤面,Hughes 椭球);变量别名见 `FIELD_ALIASES`
  (密集度 `sic_merged` / `sea_ice_area_fraction` / `ice_concentration` / `sic`;
  厚度 `sea_ice_thickness` / `ice_thickness` / `sit` / `thickness`);
- 密集度有效域 0–100(`0` 是有效值;`127`、`>100`、`<0`、NaN 为 NoData);
  厚度统一换算为米(`cm`/`mm` 自动换算,未知单位不猜测)。

## 部署

- Docker:`deploy/compose.yml` 将本目录只读挂载到容器 `/data/ice`;
- 本地开发:设置环境变量 `ICE_DATA_ROOT` 指向实际数据目录
  (例如 `F:\polar-gis\sample-data`),`ICE_ENABLED=false` 可整体关闭冰情功能;
- **不要把 NetCDF 数据文件提交到 Git**(本仓库 `.gitignore` 已排除 `*.nc`),
  大数据请通过挂载/拷贝方式提供。

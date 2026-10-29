# Navigation environment data

只读环境数据根（`NAVIGATION_DATA_ROOT`）。真实 NetCDF/GEBCO 文件不入库；本目录只提交说明文件。
海冰默认复用 `ICE_DATA_ROOT`（现有冰情图层数据），除非显式设置 `NAVIGATION_ICE_DATA_ROOT`。

```
bathymetry/  GEBCO elevation NetCDF（m，正向上；水深 = max(0, -elevation)）
ice/         neXtSIM 研究文件（siconc 0–1、sithick m）；或指向现有冰情目录
wind/        CARRA2 月度 10m_wind_speed_YYYYMM.nc + 10m_wind_direction_YYYYMM.nc
current/     TOPAZ5 日文件 Copernicus_current_YYYYMMDD.nc（vxo/vyo，原生 x/y）
wave/        WAM 日文件 Copernicus_wave_YYYYMMDD.nc（VHM0/VTPK/VMDR）
planning/    规划静态网格/离线产物（运行时代码包内已有 NEP 25km NPZ）
```

`navigation_manifest.json`（可选）用于标记数据来源与质量：

```json
{"version":1,"fields":{"wind":{"quality":"synthetic","source":"fixture","glob":"*.nc"}}}
```

合成研究数据必须标 `quality: synthetic`；`real_only` 规划会拒绝 synthetic 文件。没有 manifest 时按文件
真实数据 `real` 处理，但 issue/observation time 仍保持 unknown。

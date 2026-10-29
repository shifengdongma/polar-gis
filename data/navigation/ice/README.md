# Ice (optional neXtSIM backend)

If `NAVIGATION_ICE_BACKEND=nextsim`, place daily files `*_YYYYMMDD.nc` with 1-D latitude/longitude,
time-varying `siconc` (0–1) and optional `sithick` (m). Missing thickness is a missing component,
not zero; concentration and thickness are reported separately.

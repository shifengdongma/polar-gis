批量图层加载后，每次移动前端地图位置都需要产生多次下列请求，导致调用多次createBundleTileSource()函数以及attachWmsLayer() 函数。 当批量图层加载数量较大，会造成成千上万次网络IO请求，从而导致了前端图层加载缓慢以及卡顿问题和地图空白问题，将适当相关请求（如同一组数据集图层请求等）进行请求合并，减少前端请求次数，缓解上述批量加载卡顿空白问题

1.createBundleTileSource()

http://localhost:8088/geoserver/polar_gis/wms?REQUEST=GetMap&SERVICE=WMS&VERSION=1.3.0&FORMAT=image%2Fpng&STYLES=polar_gis%3As57_danger%2Cpolar_gis%3As57_danger&TRANSPARENT=TRUE&LAYERS=polar_gis%3As57_c110408a_1_obstrn%2Cpolar_gis%3As57_c110408a_1_uwtroc&TILED=true&WIDTH=256&HEIGHT=256&CRS=EPSG%3A3857&BBOX=-10018754.171394622%2C15028131.257091932%2C-5009377.085697311%2C20037508.342789244

这是 Bundle 组合图层 的 WMS 请求。走的是普通 WMS 路径（/geoserver/polar_gis/wms），

前端：Bundle TileWMS 源创建

  frontend/src/utils/mapRenderBundles.ts:60-75 — createBundleTileSource()

  export function createBundleTileSource(
    config: RenderBundleConfig,
    tileLoadFunction: TileLoadFunction,
  ): TileWMS {
    return new TileWMS({
      url: browserGeoServerUrl(config.serviceUrl),  // 普通 WMS，非 GWC
      params: {
        LAYERS: config.layerNames.join(','),         // 逗号拼接多层名
        TILED: true,
        STYLES: config.styles.join(','),             // 逗号拼接多样式名
      },
      // 无 VERSION 覆盖 → OL 默认 1.3.0 → 使用 CRS 参数
      crossOrigin: 'anonymous',
      transition: 0,
      tileLoadFunction,
    })
  }

2.attachWmsLayer() 

http://localhost:8088/geoserver/gwc/service/wms?REQUEST=GetMap&SERVICE=WMS&VERSION=1.1.1&FORMAT=image%2Fpng&STYLES=&TRANSPARENT=TRUE&LAYERS=polar_gis%3As57_c110408a_1_coalne&TILED=true&WIDTH=256&HEIGHT=256&SRS=EPSG%3A3857&BBOX=-10018754.171394622%2C15028131.257091932%2C-5009377.085697311%2C20037508.342789244

前端：TileWMS 瓦片源创建

frontend/src/views/MapWorkspaceView.vue:579-588 — attachWmsLayer() 函数

  const useGwc =
    ENABLE_GWC_TILES && runtime.config.renderTransport === 'gwc_wms' && !!runtime.config.tileServiceUrl
  const source = new TileWMS({
    url: browserGeoServerUrl(useGwc ? runtime.config.tileServiceUrl! : runtime.config.serviceUrl),
    params: {
      LAYERS: runtime.config.serviceLayerName,
      TILED: true,
      STYLES: runtime.config.styleName || '',
      ...(useGwc ? { VERSION: '1.1.1' } : {}),
    },
    // ...
  })
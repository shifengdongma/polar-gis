# Basemap Switcher — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 4 built-in basemap sources (OSM, Gaode, Google Maps, Tencent Maps) as frontend constants, merged with database-configured basemaps in the existing dropdown selector.

**Architecture:** A new `basemaps.ts` utility defines built-in XYZ tile sources. `MapWorkspaceView.vue` imports and merges them into `availableBaseMaps` computed property. The dropdown gets a small colored dot indicator per source. No backend changes needed.

**Tech Stack:** Vue 3 + TypeScript + OpenLayers (XYZ source) + Element Plus (el-select)

## Global Constraints

- All built-in basemaps use EPSG:3857 (Web Mercator) only
- Built-in basemaps are hidden when Arctic projection (EPSG:3413) is active
- Existing OSM fallback layer and DB basemap functionality preserved unchanged
- Silent tile load failure — no error toast for built-in sources
- Commit after each task
- Update docs/09, docs/10, docs/11 after all tasks

---

### Task 1: Create built-in basemap constants

**Files:**
- Create: `frontend/src/utils/basemaps.ts`

**Interfaces:**
- Produces: `BUILTIN_BASEMAPS: BuiltinBasemap[]` — array of 4 basemap definitions
- Produces: `BuiltinBasemap` interface — `{ id: string; name: string; mapType: 'XYZ'; urlTemplate: string; crs: 'EPSG:3857'; attribution: string; color: string }`

- [ ] **Step 1: Create the basemaps utility file**

```typescript
export interface BuiltinBasemap {
  id: string
  name: string
  mapType: 'XYZ'
  urlTemplate: string
  crs: 'EPSG:3857'
  attribution: string
  /** Dot color shown in the dropdown for quick visual identification. */
  color: string
}

export const BUILTIN_BASEMAPS: BuiltinBasemap[] = [
  {
    id: 'builtin-osm',
    name: 'OpenStreetMap',
    mapType: 'XYZ',
    urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
    crs: 'EPSG:3857',
    attribution: '© OpenStreetMap contributors',
    color: '#3b82f6',
  },
  {
    id: 'builtin-gaode',
    name: '高德地图',
    mapType: 'XYZ',
    urlTemplate: 'https://webrd0{1-4}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}',
    crs: 'EPSG:3857',
    attribution: '© 高德地图',
    color: '#22c55e',
  },
  {
    id: 'builtin-google',
    name: 'Google Maps',
    mapType: 'XYZ',
    urlTemplate: 'https://mt{0-3}.google.com/vt/lyrs=m&x={x}&y={y}&z={z}',
    crs: 'EPSG:3857',
    attribution: '© Google',
    color: '#eab308',
  },
  {
    id: 'builtin-tencent',
    name: '腾讯地图',
    mapType: 'XYZ',
    urlTemplate: 'https://rt{0-3}.map.gtimg.com/tile?z={z}&x={x}&y={y}&type=vector&styleid=0',
    crs: 'EPSG:3857',
    attribution: '© 腾讯地图',
    color: '#64748b',
  },
]
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd F:/polar-gis/frontend && npx tsc --noEmit src/utils/basemaps.ts`
Expected: No errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/utils/basemaps.ts
git commit -m "feat: add built-in basemap constants (OSM, Gaode, Google, Tencent)"
```

---

### Task 2: Merge built-in basemaps in MapWorkspaceView

**Files:**
- Modify: `frontend/src/views/MapWorkspaceView.vue`

**Interfaces:**
- Consumes: `BUILTIN_BASEMAPS, BuiltinBasemap` from `../utils/basemaps`
- Modifies: `availableBaseMaps` computed — now merges built-in + DB basemaps
- Modifies: `createConfiguredBaseLayers` — also creates layers for built-in basemaps
- Modifies: template — dropdown options show color dot + built-in/DB grouping

- [ ] **Step 1: Import built-in basemaps in the script section**

At line 78 (after the existing imports from `../utils/mapExtent`), add:

```typescript
import { BUILTIN_BASEMAPS, type BuiltinBasemap } from '../utils/basemaps'
```

- [ ] **Step 2: Convert built-in basemaps to BaseMapRecord format and merge in computed**

Replace the existing `availableBaseMaps` computed (lines 297-299):
```typescript
const availableBaseMaps = computed(() =>
  baseMaps.value.filter((baseMap) => baseMap.crs === currentCrs.value),
)
```

With:
```typescript
function builtinToBaseMapRecord(b: BuiltinBasemap): BaseMapRecord {
  return {
    id: b.id,
    name: b.name,
    mapType: b.mapType,
    urlTemplate: b.urlTemplate,
    crs: b.crs,
    attribution: b.attribution,
    isOffline: false,
    isEnabled: true,
  }
}

const availableBaseMaps = computed<Array<BaseMapRecord & { color?: string }>>(() => {
  const result: Array<BaseMapRecord & { color?: string }> = []

  // Built-in basemaps first (EPSG:3857 only)
  if (currentCrs.value === 'EPSG:3857') {
    for (const b of BUILTIN_BASEMAPS) {
      result.push({ ...builtinToBaseMapRecord(b), color: b.color })
    }
  }

  // Database basemaps follow
  for (const baseMap of baseMaps.value) {
    if (baseMap.crs === currentCrs.value) {
      result.push(baseMap)
    }
  }

  return result
})
```

- [ ] **Step 3: Update createConfiguredBaseLayers to handle built-in XYZ sources**

Replace the `createConfiguredBaseLayers` function (lines 330-372). The key change is to also iterate over built-in basemaps when building layer objects. The existing function already handles both XYZ and WMTS — we just need to feed it the built-in sources too.

Replace lines 330-372 with:
```typescript
async function createConfiguredBaseLayers() {
  const layers: BaseLayer[] = []
  const allSources: Array<BaseMapRecord & { color?: string }> = [
    ...(currentCrs.value === 'EPSG:3857'
      ? BUILTIN_BASEMAPS.map((b) => builtinToBaseMapRecord(b))
      : []),
    ...baseMaps.value,
  ]

  for (const baseMap of allSources) {
    if (baseMap.crs !== currentCrs.value) continue
    try {
      let tileLayer: TileLayer<XYZ | WMTS>
      if (baseMap.mapType === 'WMTS') {
        const response = await fetch(baseMap.urlTemplate)
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        const capabilities = new WMTSCapabilities().read(await response.text())
        const capabilityLayer = capabilities.Contents?.Layer?.[0]
        const matrixSet = capabilityLayer?.TileMatrixSetLink?.[0]?.TileMatrixSet
        if (!capabilityLayer?.Identifier || !matrixSet) throw new Error('Capabilities缺少图层或矩阵集')
        const options = optionsFromCapabilities(capabilities, {
          layer: capabilityLayer.Identifier,
          matrixSet,
        })
        if (!options) throw new Error('无法生成WMTS配置')
        tileLayer = new TileLayer({
          className: 'map-base-layer',
          opacity: 0.88,
          source: new WMTS({ ...options, crossOrigin: 'anonymous' }),
        })
      } else {
        tileLayer = new TileLayer({
          className: 'map-base-layer',
          opacity: 0.88,
          source: new XYZ({
            url: baseMap.urlTemplate,
            projection: baseMap.crs,
            crossOrigin: 'anonymous',
            attributions: baseMap.attribution || undefined,
          }),
        })
      }
      tileLayer.setVisible(false)
      configuredBaseLayers.set(baseMap.id, tileLayer)
      layers.push(tileLayer)
    } catch {
      // Only show warning for DB basemaps, not built-in ones
      if (!baseMap.id.startsWith('builtin-')) {
        ElMessage.warning(`底图"${baseMap.name}"加载失败，已与业务图层隔离`)
      }
    }
  }
  return layers
}
```

- [ ] **Step 4: Update the dropdown template to show color dots and grouping**

Replace the existing `el-select` for basemaps (lines 1371-1373):
```html
<el-select v-model="activeBaseMapId" class="full-width" placeholder="当前投影暂无配置底图" clearable @change="selectBaseMap">
  <el-option v-for="baseMap in availableBaseMaps" :key="baseMap.id" :label="`${baseMap.name} · ${baseMap.mapType}`" :value="baseMap.id" />
</el-select>
```

With:
```html
<el-select v-model="activeBaseMapId" class="full-width" placeholder="选择底图" clearable @change="selectBaseMap">
  <el-option
    v-for="baseMap in availableBaseMaps"
    :key="baseMap.id"
    :label="`${baseMap.name} · ${baseMap.mapType}`"
    :value="baseMap.id"
  >
    <span class="basemap-option">
      <span class="basemap-color-dot" :style="{ background: (baseMap as any).color || '#7896a5' }"></span>
      <span>{{ baseMap.name }}</span>
      <span class="basemap-type-tag">{{ baseMap.mapType }}</span>
    </span>
  </el-option>
</el-select>
```

- [ ] **Step 5: Verify TypeScript compiles**

Run: `cd F:/polar-gis/frontend && npx vue-tsc --noEmit 2>&1 | head -40`
Expected: No new type errors related to our changes.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/views/MapWorkspaceView.vue
git commit -m "feat: merge built-in basemaps into dropdown selector"
```

---

### Task 3: Add basemap dropdown styles

**Files:**
- Modify: `frontend/src/styles.css`

**Interfaces:**
- Consumes: CSS classes `.basemap-option`, `.basemap-color-dot`, `.basemap-type-tag`

- [ ] **Step 1: Add styles at the end of styles.css**

Append to `frontend/src/styles.css`:
```css
/* ── Basemap switcher ─────────────────────────────────────────────── */
.basemap-option {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  width: 100%;
}

.basemap-color-dot {
  flex: 0 0 10px;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  box-shadow: 0 0 0 2px rgba(255,255,255,.18);
}

.basemap-type-tag {
  margin-left: auto;
  padding: 1px 6px;
  color: #7f9baa;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: .04em;
  border: 1px solid rgba(255,255,255,.12);
  border-radius: 4px;
  background: rgba(255,255,255,.06);
}

/* Override el-select option styles inside glass panel */
.glass-panel .el-select-dropdown__item {
  padding: 8px 12px;
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/styles.css
git commit -m "style: basemap dropdown color dots and grouping tags"
```

---

### Task 4: Update documentation

**Files:**
- Modify: `docs/09-system-architecture.md`
- Modify: `docs/10-work-log.md`
- Modify: `docs/11-work-summary.md`

- [ ] **Step 1: Update system architecture doc**

Append to architecture doc under frontend section: note the new `basemaps.ts` utility and the built-in basemap merging strategy.

- [ ] **Step 2: Update work log**

Record today's tasks: built-in basemap constants, MapWorkspaceView merge, CSS styling.

- [ ] **Step 3: Update work summary**

Summarize: Added 4 built-in basemap sources (OSM, Gaode, Google, Tencent) as frontend constants, merged into dropdown with color indicators. Resolves OSM tile network failures by providing domestic alternatives.

- [ ] **Step 4: Commit and push**

```bash
git add docs/
git commit -m "docs: update architecture/log/summary for basemap switcher"
git push origin master
```

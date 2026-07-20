# 极地海洋环境信息平台

`polar-gis` 是面向极地和高纬海域的海图与海洋环境 WebGIS。一期正式支持 S-57 基础单元和连续更新，提供项目、数据、图层、查询、测量、打印和受控导出能力。

本系统不是认证 ECDIS，不替代法定航海设备。

## 仓库结构

```text
backend/    FastAPI单体后端、导入Worker和Alembic迁移
frontend/   Vue 3、Element Plus和OpenLayers前端
deploy/     Linux Docker Compose及Nginx配置
docs/       需求、架构、接口、测试和部署文档
scripts/    S-57与开发环境辅助脚本
data/       小型脱敏开发样例说明
```

## 本地开发前置服务

开发环境不要求Docker，需要手动安装：

- Python 3.12+
- Node.js当前LTS版本
- PostgreSQL + PostGIS
- GeoServer + GeoWebCache
- GDAL/OGR，且包含S-57驱动

验证GDAL：

```powershell
./scripts/check-s57.ps1 -FilePath D:\data\CELL.000
```

## 后端

```powershell
cd backend
py -3.12 -m pip install -e ".[dev]"
Copy-Item .env.example .env
py -3.12 -m alembic upgrade head
py -3.12 -m app.cli create-admin --username admin --password "polar&gis&2026!"
py -3.12 -m uvicorn app.main:app --reload --port 8000
```

另开终端启动Worker：

```powershell
cd backend
py -3.12 -m app.worker.main
```

## 前端

```powershell
cd frontend
npm install
npm run dev
```

访问 `http://localhost:5173`。开发代理会把 `/api` 转发到后端，并把 `/geoserver` 转发到本机 GeoServer。后台配置 WMTS 底图时填写 GetCapabilities 地址，XYZ 底图填写含 `{z}/{x}/{y}` 的瓦片模板。

## 使用远程虚拟机开发服务

开发配置直接连接内网虚拟机 `192.168.92.129`：PostgreSQL 使用 `5432`，GeoServer 使用 `8080`。配置已写入未提交的 `backend/.env`，不需要启动 SSH 隧道。请先确认虚拟机网络可达，再按常规方式启动 FastAPI、Worker 和前端。若本机不运行 Worker，但使用服务器 Worker 处理上传，前端 `.env` 中的 `VITE_API_PROXY_TARGET` 必须设置为 `http://192.168.92.129:8088`，使上传文件写入服务器共享存储；修改后重启 Vite。

## 验证

```powershell
cd backend
py -3.12 -m pytest
py -3.12 -m ruff check app tests

cd ../frontend
npm test
npm run build
```

## 生产部署

复制 `deploy/.env.example` 为 `deploy/.env`，替换所有密码和密钥，然后执行：

```bash
cd deploy
docker compose up -d --build
```

详细要求参见 `docs/08-deployment.md`。

## 当前外部验收项

- 提供脱敏的S-57 `.000`、`.001`、`.002`样本。
- 在安装GDAL/PostGIS/GeoServer的环境完成真实导入、更新、发布和回退验证。
- AIS和水文气象当前为明确标识的演示数据。

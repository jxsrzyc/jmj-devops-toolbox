# 部署文档

> 蓝鲸云效运维工具箱 — 本地 / Docker / Kubernetes 三种部署方式。  
> 含 SHA-256 认证系统 + Flask session，部署时需注意 session 密钥配置。

---

## 一、本地部署

### 1.1 环境要求

- Python 3.9+
- pip

### 1.2 启动步骤

```bash
cd lanqi-svc-params

# 1. 安装依赖
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 2. 启动（首次自动创建数据库 + 默认 admin 账号）
python3 app.py
# → 访问 http://127.0.0.1:5001 → 跳转到登录页
# → 默认账号: admin / admin123
```

### 1.3 常用操作

| 操作 | 命令 |
|------|------|
| 后台运行 | `nohup python3 app.py > app.log 2>&1 &` |
| 停止 | `kill $(lsof -ti:5001)` |
| 导入发版参数 | 首次启动后各模块右上角「Excel 操作 → 导入」 |

---

## 二、Docker 部署

### 2.1 文件清单

| 文件 | 用途 |
|------|------|
| `Dockerfile` | `python:3.13-slim`，最终镜像 ~200MB |
| `docker-compose.yml` | 数据挂载到宿主机 `./data/` |
| `.dockerignore` | 排除 venv/__pycache__/git |

### 2.2 构建镜像

```bash
cd lanqi-svc-params
docker build -t lanqi-svc-params:v1.0 .
```

### 2.3 docker-compose 运行（推荐）

```bash
docker-compose up -d       # http://localhost:5001
docker-compose logs -f     # 查看日志
docker-compose down        # 停止（数据保留在 ./data/）
```

---

## 三、Kubernetes 部署

### 3.1 资源文件

```
k8s/
├── pvc.yaml          # PersistentVolumeClaim（SQLite 单点存储）
├── configmap.yaml    # 应用配置（DB_PATH / FLASK_ENV / TZ）
├── deployment.yaml   # Deployment（滚动更新 + 健康检查）
└── service.yaml      # ClusterIP + 可选 LoadBalancer
```

### 3.2 快速部署

```bash
kubectl create ns tooling
kubectl apply -f k8s/ -n tooling
```

### 3.3 ⚠️ SQLite 多副本注意

SQLite 是文件数据库，不能同时被多个 Pod 写入。当前 PVC 配置为 `ReadWriteOnce`，如需要多副本必须迁移到外置数据库（PostgreSQL / MySQL）。

---

## 四、环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DB_PATH` | `./data.db` | SQLite 路径（Docker/K8s 建议 `/app/data/data.db`） |
| `SECRET_KEY` | 内置固定值 | Flask session 加密密钥（生产环境建议覆盖） |
| `PWD_SALT` | 内置固定值 | SHA-256 密码加盐（生产环境建议覆盖） |
| `FLASK_ENV` | `production` (Docker) | Flask 运行模式 |

```bash
# Docker run 示例（自定义密钥）
docker run -d \
  --name lanqi-svc-params \
  -p 5001:5001 \
  -v $(pwd)/data:/app/data \
  -e DB_PATH=/app/data/data.db \
  -e SECRET_KEY=your-random-secret-key \
  -e PWD_SALT=your-custom-salt \
  lanqi-svc-params:v1.0
```

---

## 五、健康检查

```bash
# Liveness / Readiness
curl http://localhost:5001/api/modules
# → {"code":0,"data":["..."]}

# 登录页可用
curl -s -o /dev/null -w "%{http_code}" http://localhost:5001/login
# → 200
```

---

## 六、首次部署后的数据初始化

Docker/K8s 部署后数据库是空的，需要：

```bash
# 1. 登录 admin / admin123
# 2. 各模块右上角「Excel 操作 → 导入」：
#    - 蓝鲸发版参数管理：~/Downloads/蓝鲸云效服务发版参数列表.xlsx
#    - 云效创建变更单参数：~/Downloads/云效创建变更单.xlsx
#    - 云效运行研发流程：~/Downloads/云效运行研发流程.xlsx
#    - 域名管理（jmj1995.com）：~/Downloads/生产jmj1995.com域名记录.xlsx

# 也可以直接调用 API:
curl -X POST http://localhost:5001/api/import           # 发版参数
curl -X POST http://localhost:5001/api/ci-orders/import   # 云效创建变更单
curl -X POST http://localhost:5001/api/ci-devflow/import  # 云效研发流程
curl -X POST http://localhost:5001/api/domains/import     # 域名
```

---

_最后更新：2026-08-05_
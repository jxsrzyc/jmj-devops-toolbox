# 部署文档

> 蓝鲸云效运维工具箱 — 本地 / Docker / Kubernetes 三种部署方式。  
> 含 SHA-256 认证系统 + Flask session，部署时需注意 session 密钥配置。  
> **数据库支持双模式**：生产 MySQL 8.0 / 开发 SQLite，通过 `DB_ENGINE` 一键切换。

---

## 一、本地部署

### 1.1 环境要求

- Python 3.9+
- pip
- （MySQL 模式）可访问的 MySQL 8.0 实例 + `pymysql`

### 1.2 启动步骤

```bash
cd lanqi-svc-params

# 1. 安装依赖
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt      # 含 pymysql

# 2. 配置数据库（二选一）
#    方式 A：MySQL 模式（生产）—— 首次需创建 .env（参考 .env.example）
cp .env.example .env && vim .env     # 填 DB_HOST/DB_PORT/DB_USER/DB_PASS/DB_NAME

#    方式 B：SQLite 模式（开发，零配置）
export DB_ENGINE=sqlite

# 3. 启动（首次自动建表 + 默认 admin 账号）
python3 app.py
# → 访问 http://127.0.0.1:5001 → 跳转到登录页
# → 默认账号: admin / nvcg6rBc8d#EZww6  （2026-08-31 起强密码，旧 admin123 作废）
```

> **依赖安装**：`pip install -r requirements.txt`（含 dnspython）。网络工具模块的 MTR 路由在 macOS 需 `brew install mtr`、Linux 需 `yum/apt install mtr`（Windows 自动降级为 pathping）。

> **v2.10 升级提示**：新增 `password_audit_log`（凭证密码审计）表，`init_db()` 启动时自动创建，**无需手动建表/迁移**；存量库升级只需重启服务。

### 1.3 常用操作

| 操作 | 命令 |
|------|------|
| 后台运行 | `nohup python3 app.py > app.log 2>&1 &` |
| 停止 | `kill $(lsof -ti:5001)` |
| 导入发版参数 | 首次启动后各模块右上角「Excel 操作 → 导入」 |
| SQLite → MySQL 迁移 | `python3 migrate.py`（自动备份 data.db → data.db.bak） |
| 迁移预检（不写库） | `python3 migrate.py --dry-run` |

---

## 二、Docker 部署

### 2.1 文件清单

| 文件 | 用途 |
|------|------|
| `Dockerfile` | `python:3.13-slim`，最终镜像 ~200MB |
| `docker-compose.yml` | 数据挂载到宿主机 `./data/` |
| `.dockerignore` | 排除 venv/__pycache__/git |
| `static/` | 登录页图标（Dockerfile 已 COPY） |

> **安全说明**：`data.db`（开发库）**不打包进镜像**（.dockerignore 已排除），容器首次启动 `database.py` 会自动 `init_db()` 建表，数据通过 PVC/挂载卷持久化。

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
├── configmap.yaml    # 应用配置（DB_ENGINE=sqlite / DB_PATH / FLASK_ENV / TZ）
├── secret.yaml       # 生产密钥（SECRET_KEY / PWD_SALT / CRED_SECRET_KEY）⚠️ 部署前必改
├── deployment.yaml   # Deployment（replicas: 1 + 健康检查 + Secret 挂载）
└── service.yaml      # ClusterIP + 可选 LoadBalancer
```

### 3.2 快速部署

```bash
kubectl create ns tooling

# ⚠️ 部署前先修改 k8s/secret.yaml 中的密钥（生成方式见文件头注释）
# ⚠️ 修改 k8s/deployment.yaml 中的 image 为你的镜像仓库地址

kubectl apply -f k8s/ -n tooling
kubectl rollout status deploy/lanqi-svc-params -n tooling   # 等待就绪
kubectl port-forward svc/lanqi-svc-params 5001:80 -n tooling  # 本地预览
```

### 3.3 ⚠️ SQLite 多副本注意

SQLite 是文件数据库，不能同时被多个 Pod 写入。当前 deployment 已固定 `replicas: 1`（配合 `DB_ENGINE=sqlite`）。
如需要多副本高可用，必须迁移到外置 MySQL：
1. `k8s/configmap.yaml` 中 `DB_ENGINE: "mysql"`
2. `k8s/secret.yaml` 取消注释并填写 DB_HOST / DB_PORT / DB_USER / DB_PASS / DB_NAME
3. `k8s/deployment.yaml` 中 `replicas` 改为 2+，并去掉 PVC 卷挂载

---

## 三点五、网络工具依赖说明

**网络工具**（PING检测 / 路由查询 / MTR路由）由服务端执行系统命令：

|工具|命令|所需包（Linux 容器）|
|------|------|------------------|
|PING 检测|`ping -c N -W T host`|`iputils-ping`（提供 `ping`）|
|路由查询|`traceroute -m N -q 1 -w T host`|`traceroute`|
|MTR 路由|`mtr --report -c N -j host`|`mtr`|

> **代码三端兼容**：`nettools.py` 顶部 `SYSTEM = platform.system()` 自动判断 Windows / Darwin / Linux，分别用 `ping -n` / `tracert -d` / `pathping` 兼容。**K8s 容器永远是 Linux，所以服务端永远走 Linux 分支**；客户端三端兼容对本地单机部署/开发有用。

**K8s 容器额外要求**（ICMP raw socket）：

```yaml
# k8s/deployment.yaml 容器 securityContext
securityContext:
  capabilities:
    add:
      - NET_RAW   # ping / traceroute / mtr 都用 ICMP
      - NET_ADMIN  # traceroute / mtr 设置 TTL 需要
```

Dockerfile 已 `apt-get install` 这 3 个包；如本地构建需镜像包含这些包，请确认 `Dockerfile` 第 14 行附近包含 `iputils-ping` / `traceroute` / `mtr`。

---

## 四、环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DB_ENGINE` | `mysql` | `mysql`（生产）或 `sqlite`（开发）。**K8s 部署默认 sqlite（已写入 ConfigMap），如无 MySQL 实例勿改** |
| `DB_HOST` | `127.0.0.1` | MySQL 主机（DB_ENGINE=mysql 时生效） |
| `DB_PORT` | `3306` | MySQL 端口 |
| `DB_USER` | `root` | MySQL 用户 |
| `DB_PASS` | 空 | MySQL 密码（建议放 `.env`，勿写死在代码） |
| `DB_NAME` | `ops_toolbox` | MySQL 数据库名 |
| `DB_PATH` | `./data.db` | SQLite 路径（DB_ENGINE=sqlite 时生效） |
| `SECRET_KEY` | 内置固定值 | Flask session 加密密钥（生产环境建议覆盖） |
| `PWD_SALT` | 内置固定值 | SHA-256 密码加盐（生产环境建议覆盖） |
| `CRED_SECRET_KEY` | 内置派生值 | 服务凭证密码加密密钥（44 字符 urlsafe base64，**生产必须自定义**，泄漏=凭证可解密） |
| `ALLOWED_ORIGINS` | `http://localhost:5001,http://127.0.0.1:5001` | **CORS 白名单（v2.11 新增）**——逗号分隔 origin 列表；只有这些 origin 能带 cookie 跨域调 API；生产内网访问需把对应域加进来 |
| `SESSION_COOKIE_SECURE` | `false` | **v2.11 新增**——session cookie 是否仅 HTTPS（`true` 强制 HTTPS-only；内网 HTTP 留 false） |
| `FLASK_ENV` | `production` (Docker) | Flask 运行模式 |

### LDAP 环境变量（可选，开启后本地+LDAP 双认证）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LDAP_ENABLE` | `false` | 是否启用 LDAP 认证（`true` 启用） |
| `LDAP_HOST` | 空 | LDAP 服务器地址 |
| `LDAP_PORT` | `389` | LDAP 端口（LDAPS 用 `636`） |
| `LDAP_BASE_DN` | 空 | 用户搜索基准 DN |
| `LDAP_BIND_USER` | 空 | Bind 服务账号 DN |
| `LDAP_BIND_PASS` | 空 | Bind 服务账号密码 |
| `LDAP_AUTH_FILTER` | `(&(objectClass=inetOrgPerson)(uid=%s))` | 登录认证过滤（openldap） |
| `LDAP_USER_FILTER` | 同 AUTH_FILTER | 用户信息过滤 |
| `LDAP_TLS` | `false` | 使用 LDAPS（636） |
| `LDAP_STARTTLS` | `false` | 使用 STARTTLS |
| `LDAP_DEFAULT_PERMS` | `release` | LDAP 用户首次登录默认权限串（legacy 快照，仅在默认角色不存在时兜底生效） |
| `LDAP_DEFAULT_ROLE` | `发版` | LDAP 用户首次登录 JIT 自动挂载的内置角色名（v2.16，角色不存在则回退 `LDAP_DEFAULT_PERMS`） |

> **LDAP 认证说明**：本地账号（含 admin）走本地 SHA-256 校验；LDAP 账号首次登录自动创建本地记录（默认挂「发版」角色，仅蓝鲸发版参数管理权限），之后由管理员按需授权。LDAP 密码不落库；LDAP 服务器异常不影响本地账号登录。

> **v2.15 RBAC 角色权限说明**：
> - 新增 `roles` 表（启动自动建表）+ `users.role_ids` 列（自动补列），**无需手工迁移**；首次启动自动 seed 内置角色（v2.16 起 5 个：管理员/发版/运维/开发/测试），并把存量用户的 `permissions` 串自动转换为「迁移-<权限串>」角色挂接
> - 用户授权入口：「系统管理 → 用户管理 → 用户列表 → 编辑」勾选角色；角色权限配置：「用户管理 → 角色管理」权限树勾选（支持子标签级，如仅 IP 查询、仅生成器）
> - 权限变更（改角色权限/改用户角色）**即时生效**，受影响用户无需重新登录
> - `LDAP_DEFAULT_ROLE` 指定的角色不存在时，回退 `LDAP_DEFAULT_PERMS` 权限串（无角色用户兜底）

> 配置通过项目根目录 `.env` 文件加载（优先级低于系统环境变量）。**密码请放 .env，不要提交到代码仓库。**

```bash
# Docker run 示例（MySQL 模式 + 自定义密钥）
docker run -d \
  --name lanqi-svc-params \
  -p 5001:5001 \
  -e DB_ENGINE=mysql \
  -e DB_HOST=mysql-dev-001.example.com \
  -e DB_PORT=3306 \
  -e DB_USER=ops_toolbox \
  -e DB_PASS=your-password \
  -e DB_NAME=ops_toolbox \
  -e SECRET_KEY=your-random-secret-key \
  -e PWD_SALT=your-custom-salt \
  lanqi-svc-params:v1.0
```

---

## 五、健康检查

```bash
# K8s 探针：
#   readiness: GET /api/modules （查库，数据库健康才就绪）
#   liveness:  GET /login        （进程存活）

# 本地验证
curl http://localhost:5001/api/modules   # → {"code":0,"data":["..."]}
curl -s -o /dev/null -w "%{http_code}" http://localhost:5001/login  # → 200
```

---

## 六、SQLite → MySQL 数据迁移

> 2026-08-06 起生产环境使用 MySQL 8.0（`ops_toolbox`），旧 SQLite 数据已迁移完成。

### 迁移步骤（新环境）

```bash
# 1. 备份（脚本自动执行）
# 2. 预检（只读，不写库）
python3 migrate.py --dry-run

# 3. 正式迁移（逐表 TRUNCATE+INSERT，保留自增 id，行数校验）
python3 migrate.py
```

### 迁移说明

- 自动备份 `data.db` → `data.db.bak`，**迁移完确认无误前不要删备份**
- 6 张表：service_params / service_credentials / domains / ci_orders / ci_devflow / users
- users 表密码 hash 原样搬移（SHA-256 与数据库无关）
- 迁移前后自动校验行数一致性

---

## 七、首次部署后的数据初始化

Docker/K8s 部署后数据库是空的，需要：

```bash
# 1. 登录 admin / nvcg6rBc8d#EZww6
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

## 八、健康检查

```bash
# K8s 探针：
#   readiness: GET /api/modules （查库，数据库健康才就绪）
#   liveness:  GET /login        （进程存活）

# 本地验证
curl http://localhost:5001/api/modules   # → {"code":0,"data":["..."]}
curl -s -o /dev/null -w "%{http_code}" http://localhost:5001/login  # → 200
```

---

_最后更新：2026-08-07（v1.3 凭证模块）_
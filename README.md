# 蓝鲸云效运维工具箱

> 基于 Flask + MySQL 8.0（兼容 SQLite）的内部运维工具集，统一管理发版参数、CI/CD 配置、服务凭证、域名及 SSL 证书。

---

## 一、项目简介

本项目把分散在多个 Excel 表格中的运维参数集中到 Web 端，支持可视化筛选、批量复制、导入导出。目前包含 **发版管理**（3 个子标签）、**服务凭证管理**、**域名管理**，以及管理员专属的**用户管理**模块，带完整的 SHA-256 身份认证系统。

| 模块 | 记录数 | 数据来源 |
|------|--------|----------|
| 蓝鲸发版参数管理 | 194 | `蓝鲸云效服务发版参数列表.xlsx` |
| 云效创建变更单参数 | 194 | `云效创建变更单.xlsx` |
| 云效运行研发流程参数 | 194 | `云效运行研发流程.xlsx` |
| 服务凭证管理 | 5+ | 手动录入 + 导入 |
| 域名管理 (jmj1995.com) | 129 | `生产jmj1995.com域名记录.xlsx` |
| 用户管理 | 管理员专属 | 内置 admin 账号 |

---

## 二、技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| 后端 | Python 3 + Flask | Flask session + werkzeug |
| 数据库 | **双模式：MySQL 8.0（生产）/ SQLite（开发）** | `DB_ENGINE` 一键切换，pymysql 直连 |
| 前端 | HTML + Tailwind CSS CDN + Vanilla JS | 零构建工具 |
| 认证 | SHA-256（零依赖） + Flask session | 用户级标签页权限控制 |
| Excel | pandas + openpyxl | 导入 / 导出 / 模板下载 |
| 登录页 | Canvas 物理引擎 | 真实 PNG 图标 + 碰撞 + 鼠标轨迹 |

---

## 三、目录结构

```
lanqi-svc-params/
├── app.py                  # Flask 主应用（路由 + 全部 API）
├── database.py             # 数据库封装层（双模式：SQLite / MySQL 8.0）
├── auth.py                 # 身份认证 + 权限管理（SHA-256）
├── excel_utils.py          # Excel 生成工具（导出/模板）
├── models.py               # 数据模型类
├── migrate.py              # SQLite → MySQL 数据迁移脚本
├── seed.py                 # 种子数据导入（❌不要轻易运行！）
├── requirements.txt        # 依赖清单
├── .env / .env.example     # 数据库配置（密码放 .env，勿提交）
├── data.db                 # SQLite 数据库（开发模式 / 迁移数据源）
├── static/
│   └── icons/              # 登录页浮动图标素材
├── templates/
│   ├── login.html          # 登录页（Canvas 物理引擎）
│   └── index.html          # 主页面（单页 SPA）
└── README.md
```

---

## 四、快速启动

### 1. 环境要求

- Python 3.9+
- macOS / Linux / Windows

### 2. 安装 + 启动

```bash
cd lanqi-svc-params
pip install -r requirements.txt   # flask, flask-cors, pandas, openpyxl, pymysql

# 方式 A：MySQL 模式（生产）
cp .env.example .env && vim .env  # 填写 DB_HOST/DB_PORT/DB_USER/DB_PASS/DB_NAME
python3 app.py

# 方式 B：SQLite 模式（开发，零配置）
DB_ENGINE=sqlite python3 app.py

# → http://127.0.0.1:5001 → 跳转到登录页
```

> 首次启动自动建表 + 默认 admin 账号。SQLite 旧数据迁移到 MySQL：`python3 migrate.py`（详见 DEPLOY.md）。

### 3. 默认账号

| 用户名 | 密码 | 权限 |
|--------|------|------|
| `admin` | `admin123` | `*` — 管理员（全部功能 + 用户管理） |

### ⚠️ 数据库安全提示

**不要执行 `rm data.db && python3 seed.py`！**
`seed.py` 会清空 `service_params` 表再导入。要添加新模块只需在 `database.py` 的 `init_db()` 中新增 `CREATE TABLE IF NOT EXISTS`，系统会自动初始化新表而不影响旧数据。

首次启动时数据库不存在，`init_db()` 会自动创建 6 张表 + 默认 admin 账号。

---

## 五、功能说明

### 5.1 发版管理（3 个子标签）

侧边栏「发版管理」点击展开：

- **蓝鲸发版参数管理** — 业务模块/服务/创建变更单参数/运行研发流程参数/环境
- **云效创建变更单参数** — 应用交付服务/环境/发版分支/仓库标识符
- **云效运行研发流程参数** — 应用交付服务/环境/流程序列号/阶段序列号

每个子标签都支持：筛选（关键词 + 环境） + 增删改 + Excel 三件套。

### 5.2 服务凭证管理

18 个字段：服务名/凭证类型/访问链接/用户名/密码/SSH密钥/API Token/内外网地址/数据库名/负责人/过期时间等，支持过期提醒和状态筛选。

### 5.3 域名管理

jmj1995.com 的子域名管理（129 条/5 个大区），5 种类型（apisix/higress/nginx/alb/供应商），8 种环境。SSL 证书到期统计（正常/30天内过期/已过期）。

### 5.4 用户管理（仅管理员）

「系统管理」→「用户管理」页面可以可视化增删用户、重置密码、配置标签页权限（release/credentials/domains 自由组合）。

侧边栏左下角新增**用户面板**：点击头像弹出个人信息（用户名/显示名/权限范围）+ 修改密码 + 退出登录。

### 5.5 Excel 导入/导出/模板

所有模块都在右上角「Excel 操作」下拉菜单：

```
📥 导入 Excel       ← 覆盖/增量导入当前模块数据
📤 导出当前数据     ← 当前筛选结果导出为 .xlsx
📋 下载导入模板     ← 含表头 + 示例数据的空模板
```

### 5.6 登录页

- **20+ 个真实 PNG 运维图标**（K8s/AI/安全/数据库/Docker/网关/终端等）自由漂浮
- 重力物理引擎（可开关）+ 鼠标拖动图标 + 粒子轨迹
- 图标撞击登录框反弹、互相碰撞传递动量
- 快捷键：`G` 重力开关 / `R` 刷新 / `空格` 重力方向

---

## 六、数据库设计（6 张表）

### `service_params`
发版参数管理：id, business_module, service_name, create_change_params, run_devflow_params, env, created_at, updated_at

### `ci_orders`
云效创建变更单：id, delivery_service, env, branch, repo_sn, created_at, updated_at

### `ci_devflow`
云效运行研发流程：id, delivery_service, env, wf_sn, stage_sn, created_at, updated_at

### `service_credentials`
服务凭证（18 字段）：id, service_name, credential_type, access_url, username, password, ssh_key, api_token, internal_url, internal_port, external_url, external_port, db_name, owner, expires_at, status, notes, created_at, updated_at

### `domains`
域名管理：id, root_domain, region, service_name, domain_name, domain_type, env, cert_progress, cert_expiry, notes, created_at, updated_at

### `users`
用户认证：id, username, password_hash (SHA-256), display_name, permissions, is_active, created_at

---

## 七、API 端点

### 发版参数
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/modules` | 业务模块列表 |
| GET | `/api/services` | 查询（支持 module/env/keyword/page） |
| POST/PUT/DELETE | `/api/services[/<id>]` | CRUD |
| GET | `/api/services/export-xlsx` | 导出 xlsx |
| GET | `/api/services/template` | 导入模板 |

### 云效创建变更单 / 研发流程
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/ci-orders` | 查询（keyword/env/page） |
| POST/PUT/DELETE | `/api/ci-orders[/<id>]` | CRUD |
| POST | `/api/ci-orders/import` | Excel 导入 |
| GET | `/api/ci-orders/export` | xlsx 导出 |
| GET | `/api/ci-orders/template` | 模板下载 |

（`/api/ci-devflow` 完全相同的端点结构）

### 认证 / 用户
| 方法 | 路径 | 说明 |
|------|------|------|
| GET/POST | `/login` | 登录页 / 提交 |
| GET | `/logout` | 登出 |
| GET | `/api/me` | 当前用户信息 |
| GET/POST | `/api/users` | 用户列表 / 新增 |
| PUT | `/api/users/<id>` | 编辑权限 |
| POST | `/api/users/<id>/reset-pwd` | 重置密码 |
| DELETE | `/api/users/<id>` | 删除 |

（域名/凭证的 API 端点省略，与上述同模式）

---

## 八、版本记录

### v1.1 (2026-08-06)
- 🚀 **数据库升级 MySQL 8.0**：双模式切换（`DB_ENGINE=sqlite|mysql`），pymysql 直连，生产环境数据已迁移
- 🚀 新增 `migrate.py` 数据迁移脚本（备份 → dry-run → 逐表迁移 → 行数校验）
- ✨ 新增 `.env` 配置（数据库连接信息，密码不入代码）
- ✨ 侧边栏左下角新增用户面板（个人信息 + 修改密码 + 退出登录）
- ✨ 新增 `/api/change-password` 修改密码接口（验证旧密码）
- 🔧 表格操作列优化：蓝鲸发版参数/域名/用户管理操作按钮横排
- 🔧 页面自适应屏幕：表格内部滚动、分页器钉底、表头吸顶
- 🔧 移除侧边栏左下角"数据: xx 条 / xx 模块"小字
- 🔧 浏览器标题改为「运维工具箱」
- 🔧 删除弹窗统一重构 + 弹窗互斥管理（修复多弹窗叠加）

### v1.0 (2026-08-05)
- ✨ 新增云效创建变更单参数 + 云效运行研发流程参数子标签（各 194 条）
- ✨ 新增 sha256 身份认证 + 多用户 + 标签页级权限
- ✨ 新增酷炫 Canvas 物理引擎登录页
- ✨ 新增用户管理（可视化增删改查）
- ✨ 新增域名管理大区字段 + CDN 环境修正
- ✨ 新增所有模块 Excel 导入/导出/模板三件套
- ✨ 补全 jmj1995.com 的 5 个子表数据导入
- ✨ 补全筛选 bug 修复（下拉不重复加载）

### v0.9 (2026-08-04)
- flask + sqlite 初版：发版参数管理 / 服务凭证管理 / 域名管理

---

## 九、常见问题

**Q: 数据库重置？**
A: **不建议！** MySQL 模式不要清空 ops_toolbox；SQLite 模式不要删除 data.db。需要新模块用 `init_db()` 自动建表，新数据用各模块的 `/import` API。

**Q: seed.py 可以跑吗？**
A: **已有数据时不会直接执行**。需要 `python3 seed.py --force` 强行覆盖，且它只影响 `service_params` 表。

**Q: 如何添加新用户？**
A: admin 登录 → 用户管理 → 新增用户 → 设置权限组合。

**Q: 如何限制某用户只能看发版管理？**
A: 编辑该用户的权限字段为 `release`，他登录后就只能看到「发版管理」菜单。

**Q: SQLite 和 MySQL 怎么切换？**
A: 改 `.env` 里的 `DB_ENGINE`（`mysql` 或 `sqlite`）重启即可；系统环境变量优先级更高。SQLite 数据迁 MySQL 用 `python3 migrate.py`。

---

_最后更新：2026-08-06_
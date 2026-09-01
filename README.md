# 蓝鲸云效运维工具箱

> 基于 Flask + MySQL 8.0（兼容 SQLite）的内部运维工具集，统一管理发版参数、CI/CD 配置、服务凭证、域名及 SSL 证书。

---

## 一、项目简介

本项目把分散在多个 Excel 表格中的运维参数集中到 Web 端，支持可视化筛选、批量复制、导入导出。目前包含 **发版管理**（4 个子标签）、**服务凭证管理**、**域名管理**、**网络工具**、**运维小工具**，以及管理员专属的**用户管理**模块，带完整的 **SHA-256 本地认证 + 公司 LDAP 双认证源**。

| 模块 | 记录数 | 数据来源 |
|------|--------|----------|
| 蓝鲸发版参数管理 | 194 | `蓝鲸云效服务发版参数列表.xlsx` |
| 云效创建变更单参数 | 194 | `云效创建变更单.xlsx` |
| 云效运行研发流程参数 | 194 | `云效运行研发流程.xlsx` |
| 发版修复记录 | 47 | `2026 年全年云效新发版工单数据汇总.docx` |
| 服务凭证管理 | 64 | 手动录入 + 导入 |
| 域名管理 (jmj1995.com) | 129 | `生产jmj1995.com域名记录.xlsx` |
| 用户管理 | 管理员专属 | 内置 admin 账号 |

---

## 二、技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| 后端 | Python 3 + Flask | Flask session + werkzeug |
| 数据库 | **双模式：MySQL 8.0（生产）/ SQLite（开发）** | `DB_ENGINE` 一键切换，pymysql 直连 |
| 前端 | HTML + Tailwind CSS CDN + Vanilla JS | 零构建工具 |
| 认证 | **SHA-256 本地认证 + LDAP 双认证源** | 本地账号 + 公司 LDAP 账号均可登录 |
| Excel | pandas + openpyxl | 导入 / 导出 / 模板下载 |
| 登录页 | Canvas 物理引擎 | 真实 PNG 图标 + 碰撞 + 鼠标轨迹 |

---

## 三、目录结构

```
lanqi-svc-params/
├── app.py                  # Flask 主应用（路由 + 全部 API）
├── database.py             # 数据库封装层（双模式：SQLite / MySQL 8.0）
├── auth.py                 # 身份认证 + 权限管理（SHA-256 本地 + LDAP）
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
| `admin` | `nvcg6rBc8d#EZww6` | `*` — 管理员（全部功能 + 用户管理） |

> 🔑 **2026-08-31 起 admin 密码已升级为强密码**（旧密码 `admin123` 已作废）；`database.py` 初始化种子同步更新（仅新库生效）。

### ⚠️ 数据库安全提示

**不要执行 `rm data.db && python3 seed.py`！**
`seed.py` 会清空 `service_params` 表再导入。要添加新模块只需在 `database.py` 的 `init_db()` 中新增 `CREATE TABLE IF NOT EXISTS`，系统会自动初始化新表而不影响旧数据。

首次启动时数据库不存在，`init_db()` 会自动创建 6 张表 + 默认 admin 账号。

---

## 五、功能说明

### 5.1 发版管理（4 个子标签）

侧边栏「发版管理」点击展开：

- **蓝鲸发版参数管理** — 业务模块/服务/创建变更单参数/运行研发流程参数/环境
- **云效创建变更单参数** — 应用交付服务/环境/发版分支/仓库标识符
- **云效运行研发流程参数** — 应用交付服务/环境/流程序列号/阶段序列号
- **发版修复记录** — 工单重复发版原因汇总：发布时间/星期/迭代日重复发版/技术线/重复发布工单（超链接）/重复发布服务/重复发布类型/重复发布原因

每个子标签都支持：筛选（关键词 + 环境/技术线/类型/日期范围） + 增删改 + Excel 三件套。
发版修复记录额外支持：统计卡片（总数/技术线数/服务数/迭代日重复次数）、按发布时间升序排列、序号自动连续（新增时库内 seq_no 自动取 max+1）。

### 5.2 服务凭证管理（6 个环境子标签 · 侧边栏）

侧边栏「服务凭证管理」可展开，下挂 **6 个环境子标签** + 「全部」：
- 超融合电信开发环境 / 超融合南沙生产环境 / 预生产环境 / 国内生产环境 / 新加坡生产环境 / 北美生产环境

**双搜索框**：
- **业务名称** 框 — 仅匹配业务名称字段
- **关键词** 框 — 模糊匹配账号/地址/备注等字段

- 统一字段：业务名称/应用类型/版本/服务连接地址/内网地址/内网端口/公网地址/公网端口/账号/密码/备注（各环境没有的字段留空）
- 🔐 **密码加密存储**（AES-256-GCM / Fernet），列表只显示 `●●●●●●●●`，导出自动脱敏，导入 Excel 时**跳过密码列**
- 端口导入时**内外网端口保持一致**（同一端口），后续可在编辑弹窗中分别调整
- Excel 导入读取 `~/Downloads/开发生产服务器信息.xlsx`（6 个子表自动映射到 6 个环境）

### 5.3 域名管理

jmj1995.com 的子域名管理（129 条/5 个大区），5 种类型（apisix/higress/nginx/alb/供应商），8 种环境。SSL 证书到期统计（正常/30天内过期/已过期）。

### 5.4 网络工具（9 个子标签 · 跨平台）

侧边栏「网络工具」可展开，下挂 **9 个子工具**（全部支持 Windows / macOS / Linux）：

| 子工具 | 说明 | 技术实现 |
|--------|------|---------|
| IP 查询 | IP/域名归属地、运营商、ASN | 第三方免费 API（ip-api.com） |
| PING 检测 | ICMP 连通性、延迟、丢包率 | 系统 ping 命令（Windows `-n` / macOS `-c`） |
| TCPing | TCP 端口连通性、握手耗时 | 纯 Python socket（跨平台） |
| DNS 查询 | A/AAAA/CNAME/MX/NS/TXT 等多记录 | dnspython + 多公共 DNS |
| 路由查询 | Traceroute 逐跳追踪 | 系统 traceroute/tracert 命令 |
| MTR 路由 | 去程丢包率与延迟分析 | macOS/Linux: mtr -j；Windows: pathping 降级 |
| CDN 查询 | CDN 服务商识别 | CNAME 特征规则库 + IP ASN 归属库 |
| Whois 查询 | 域名注册信息（注册商/注册/到期/状态） | RDAP 公共 API（无 key、跨平台统一） |
| SSL 检测 | TLS 证书信息 + 协议版本支持矩阵 | 纯 Python socket/ssl + cryptography 解析 |

**安全设计**：输入校验（域名/IP 白名单 + 内网/回环黑名单防 SSRF）、subprocess 强制超时、`shell=False`、权限控制（`nettools` 权限，可在用户管理配置）。

### 5.5 运维小工具（14 个子标签）

侧边栏「运维小工具」可展开，下挂 **14 个子工具**（权限 `utils`，可在用户管理配置）：

| 子工具 | 说明 | 技术实现 |
|--------|------|---------|
| CIDR 子网计算器 | 网络/广播/可用主机/掩码计算 | Python `ipaddress` |
| 时间戳换算 | Unix 时间戳 ⇄ 人类时间（双向、时区可选） | Python datetime |
| JSON 格式化 | 美化/压缩/语法校验 | Python json |
| 编解码/哈希 | Base64/URL 编解码 + MD5/SHA1/256/512 | Python base64/hashlib |
| Webhook 测试 | 向任意 URL 发送测试请求看响应 | urllib + 防 SSRF 校验 |
| 批量端口连通检查 | 表格批量 TCPing（最多 50 条） | 复用 nettools.tcping |
| 批量PING检测 | 批量 PING 多个 IP/域名（最多 50 条，10 线程并发） | 复用 nettools.ping_detect + ThreadPoolExecutor |
| HTTP 健康检查 | URL 状态码/耗时/响应头/返回体 | urllib |
| 证书批量到期监控 | 批量 SSL 证书剩余天数（最多 100 条） | 复用 nettools.ssl_inspect |
| K8s Yaml 检测 | YAML 语法 + 资源必填字段/规范检查（多文档） | pyyaml |
| Curl 请求调试 | 粘贴 curl 命令执行看响应 | 安全重组（仅 http/https + 参数白名单） |
| 文本比较 | 逐行 Diff 对比（粘贴/上传，忽略空白/大小写） | 纯前端 LCS 算法 |
| 文本去重 | 按分隔符（换行/逗号/分号/Tab/自定义）去重 | 纯前端 Set 去重 |
| 生成器 | 密码 / 密码短语 / 用户名 三合一 | 纯前端 crypto 安全随机 + 内置 5000 词库 |
| 生成器历史记录 | 弹窗式（最近 20 条，localStorage） | 纯前端，集成在生成器页面右上角 |
| 科学计算器 | 表达式计算：四则/括号/幂/阶乘/百分号 + 科学函数（sin/cos/tan/log/ln/√ 等）+ 角度/弧度切换 | 纯前端手写表达式解析器（词法分析 + 递归下降求值） |

**安全设计**：curl/webhook/http 仅允许 http(s) 且禁止内网/回环目标（防 SSRF）；curl 参数白名单（-X/-H/-d/-u/-k/-s/-w 等），`-o` 仅允许 /dev/null。

### 5.7 用户管理（仅管理员）

「系统管理」→「用户管理」页面可以可视化增删用户、重置密码、配置标签页权限（release/credentials/domains/nettools 自由组合），表格中标识每个用户的认证方式（**本地** / **LDAP**）。

侧边栏左下角新增**用户面板**：点击头像弹出个人信息（用户名/显示名/权限范围）+ 修改密码（LDAP 用户不显示）+ 退出登录。

### 5.8 LDAP 单点登录

支持**公司 LDAP 账号**和**本地手动创建账号**双认证源登录：

| 场景 | 行为 |
|------|------|
| 本地账号（如 admin） | 走本地 SHA-256 校验，完全不受影响 |
| LDAP 账号首次登录 | 自动在 users 表创建记录（JIT 开通），**默认仅发版管理权限**，管理员可后续调整 |
| LDAP 账号再次登录 | 直接 LDAP 校验，显示名自动同步 |

- 配置在 `.env`：`LDAP_ENABLE / LDAP_HOST / LDAP_PORT / LDAP_BASE_DN / LDAP_BIND_USER / LDAP_BIND_PASS / LDAP_AUTH_FILTER / LDAP_USER_FILTER / LDAP_TLS / LDAP_STARTTLS / LDAP_DEFAULT_PERMS`
- AuthFilter 支持占位符：openldap `(&(uid=%s))` / AD `(&(sAMAccountName=%s))`
- LDAP 密码不落库，本地密码置随机值（不走本地校验）
- LDAP 服务器异常时不影响本地账号登录（认证带异常兜底）

### 5.6 Excel 导入/导出/模板

所有模块都在右上角「Excel 操作」下拉菜单：

```
📥 导入 Excel       ← 覆盖/增量导入当前模块数据
📤 导出当前数据     ← 当前筛选结果导出为 .xlsx
📋 下载导入模板     ← 含表头 + 示例数据的空模板
```

### 5.9 登录页

- **20+ 个真实 PNG 运维图标**（K8s/AI/安全/数据库/Docker/网关/终端等）自由漂浮
- 重力物理引擎（可开关）+ 鼠标拖动图标 + 粒子轨迹
- 图标撞击登录框反弹、互相碰撞传递动量
- 快捷键：`G` 重力开关 / `R` 刷新 / `空格` 重力方向

---

## 六、数据库设计

### `service_params`
发版参数管理：id, business_module, service_name, create_change_params, run_devflow_params, env, created_at, updated_at

### `ci_orders`
云效创建变更单：id, delivery_service, env, branch, repo_sn, created_at, updated_at

### `ci_devflow`
云效运行研发流程：id, delivery_service, env, wf_sn, stage_sn, created_at, updated_at

### `release_fix_records`
发版修复记录（工单重复发版原因汇总）：id, **seq_no(序号，新增自动 max+1)**, release_date(发布时间), weekday(星期), iter_day_dup(迭代日重复发版 是/否), tech_line(技术线), work_order(重复发布工单), **work_order_url(工单链接)**, service_name(重复发布服务，支持多行), release_type(重复发布类型), fix_reason(重复发布原因，长文本), created_at, updated_at

### `service_credentials`
服务凭证（6 环境统一表）：id, **business_purpose(业务用途, 默认'通用服务')**, **env**, service_name(业务名称), **service_provider(服务供应商)**, **app_type, version**, username(账号), **password(加密存储)**, internal_url, internal_port, external_url, external_port, notes, created_at, updated_at

### `cred_business_colors`
业务用途颜色配置（可自定义）：id, purpose(唯一), color(#RRGGBB), updated_at

### `domains`
域名管理：id, root_domain, region, service_name, domain_name, domain_type, env, cert_progress, cert_expiry, notes, created_at, updated_at

### `users`
用户认证：id, username, password_hash (SHA-256), display_name, permissions, is_active, **auth_source (local/ldap)**, created_at

### `password_audit_log`
凭证密码查看审计（v2.10 新增，**永久保留不滚动清理**）：id, username(查看人), credential_id, service_name(业务名冗余快照), env, client_ip(来源 IP), user_agent, created_at(查看时间)

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

### 发版修复记录
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/fix-records` | 查询（keyword/tech_line/release_type/weekday/date_from/date_to/page） |
| GET | `/api/fix-records/filters` | 筛选下拉选项（技术线/类型/星期去重） |
| GET | `/api/fix-records/<id>` | 单条详情 |
| POST | `/api/fix-records` | 新增（seq_no 缺省自动取 max+1） |
| PUT | `/api/fix-records/<id>` | 编辑 |
| DELETE | `/api/fix-records/<id>` | 删除 |
| POST | `/api/fix-records/import` | Excel 导入（中文表头映射，读取 `~/Downloads/发版修复记录.xlsx`） |
| GET | `/api/fix-records/export` | 导出当前筛选结果 |
| GET | `/api/fix-records/template` | 下载导入模板 |

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

### v2.11.1 (2026-09-01)
- 🎨 **登录页图标飘动动画优化（柔和漂浮模式）**：修复飘动"笨重顿挫 + 偏快"问题
  - 移除 `minSpeed` 低俗度踹脚脉冲逻辑（原速度 <1.0 时每帧强制踢一脚 → "慢→踢→快→慢"节律性抖动，肉眼明显）
  - 参数调整：`friction` 0.985→**0.99**（衰减更慢、速度柔和）、`windStrength` 0.06→**0.07**（柔风扰动持续带动）、起始速度 ±4→**±3.2**、旋转速度 0.04→**0.012**、撞墙反弹 `×0.92+0.4`→**×0.88 软反弹**（去掉强制加速、顺滑）、背景残影 0.25→**0.08**（拖尾变轻）
  - 效果：慢速连续漂浮、无顿挫；速度档位经用户 3 轮反馈定稿（0.07/3.2）

### v2.11 (2026-08-31)
- 🔐 **安全加固 · B+C 项落地**
  - **B CORS 白名单**：`CORS(app, supports_credentials=True, origins=ALLOWED_ORIGINS)`；从 `.env` 读 `ALLOWED_ORIGINS`（逗号分隔）；默认仅 `http://localhost:5001, http://127.0.0.1:5001`；恶意 origin 不再自动带 session cookie（防 CSRF）
  - **C session cookie 加固**：`HTTPONLY=True`（防 XSS 读 cookie）、`SAMESITE='Lax'`（防 CSRF）、`PERMANENT_SESSION_LIFETIME=8h`（8 小时过期）；`SESSION_COOKIE_SECURE` 由 `.env` 控制（内网 HTTP 默认 false，生产 HTTPS 建议 true）
  - **secret_key 升级**：优先 `.env` `SECRET_KEY` → `.env` `CRED_SECRET_KEY` → 硬编码默认值（启动 warn 提醒）
- 🕒 **审计表时间改 `YYYY-MM-DD HH:MM:SS`**：前端 `formatDateTime()` 函数（兼容 ISO/RFC1123/MySQL 字符串），后端 JSON 序列化零改动（不影响其他模块日期字段）
  - 🐛 **热修复**：Flask 默认 `DefaultJSONProvider` 把 naive datetime 序列化为 RFC 1123（带 `GMT` 后缀 = 声明 UTC），原 fallback 用本地 `getHours()` 在 UTC+8 浏览器上把 `17:16` 翻成次日 `01:16`（偏差 16 小时、跨日）。改为 `getUTCHours()` 系列后与浏览器时区无关，数据库存的数值原样显示

### v2.10 (2026-08-31)
- 🔐 **凭证密码查看审计（安全加固 · 方案 A）**：`reveal-password` 接口每次解密返回明文密码时**强制写入审计日志**——记录 用户/凭证ID/业务名/环境/来源IP/User-Agent/时间
- ✨ 新表 `password_audit_log`（SQLite/MySQL 双模式自动建表；**不设 200 条滚动清理，永久保留**取证）
- ✨ 用户管理页面改为 **「用户列表 | 密码审计」双 Tab**：密码审计表格倒序展示最近 100 条（时间/用户/来源IP/凭证ID/业务名/环境/UA），仅管理员可见
- 🔌 新增 `GET /api/audit/password-reveal?limit=N`（`@require_perm("admin")`，最多 500 条）；审计写入端 `db.add_password_audit(...)` 失败静默降级（不影响密码复制主流程）
- 📌 安全说明：谁在何时查看了哪条凭证密码**从此留痕可查**；该表数据仅通过 admin 审计接口展示，不进入首页最近活动

### v2.9 (2026-08-28)
- 🚀 CIDR 子网计算器新增 **「IP 范围 → 网段」** Tab：输入起始/结束 IP（或直接粘贴 `120.236.160.1 - 120.236.175.254`，自动解析 `-`/`~`/`到`/`—` 分隔）→ 同时返回**最小覆盖**（推荐，1 个 CIDR 包住整个范围）和**精确拆分**（范围严格不超出）
- ✨ **最小覆盖**（默认展示，绿色高亮）：贪心选最大对齐块，CIDR 数最少，适合防火墙/安全组配置（允许范围外少量 IP）。例：`120.236.160.1-120.236.175.254` → **`120.236.160.0/20`**（多含 2 IP）；`58.248.231.217-222` → **`58.248.231.216/29`**（多含 2 IP）；`192.168.1.0-255` → `192.168.1.0/24`（边界对齐，0 多余）
- ✨ **精确拆分**（可切换展开）：贪心对齐，块严格在 [start, end] 内，例 `120.236.160.1-175.254` 拆 22 个
- ✨ 结果区：统计卡片（起始/结束 IP、范围总 IP、网段数）+ 单行复制 + 一键复制全部 CIDR（换行分隔）；切换按钮「📋 查看精确拆分（N 个）」/「🔙 返回最小覆盖」
- ✨ 校验：起始>结束、IPv4/IPv6 混用、非法 IP 均报错；`opsutils.range_to_cidrs` + `POST /api/utils/range-to-cidrs`

### v2.8 (2026-08-26)
- 🎨 服务凭证管理搜索栏 3 个控件（业务名称/业务用途/关键词）label 区统一 `min-h-[1.25rem]`，修复「业务名称」带「管理」按钮撑高导致三个输入框不在同一水平线的问题
- ✨ 「业务环境汇总」（全部视图）新增 **环境** 列（第 3 列，宽 8rem），凭证来源环境一目了然；其余环境子标签不显示该列（动态 colgroup/表头/colspan）
- ✨ 环境列显示**简写**（电信开发/南沙生产/私有云测试/私有云生产/预生产/国内生产/新加坡生产/北美生产），悬停 `title` 显示完整环境名（`ENV_SHORT` 映射表）
- 🐛 **网络工具 Whois 双根因修复**：① 子域名自动提取注册域（eTLD+1，`MULTI_PART_TLDS` 覆盖 .com.cn/.co.uk/.com.au 等 20+ 双段 TLD）——RDAP 协议只查注册域，`gateway.jmj1995.com` 自动转 `jmj1995.com`；② `.cn/.com.cn/.中国` 等中国国家 TLD 走 **CNNIC 43 端口传统 WHOIS**（`whois.cnnic.cn:43` 纯 socket）——rdap.org 依赖 IANA bootstrap 表，CNNIC 未注册导致 404
- ✨ Whois 前端升级：子域名自动转换顶部黄条提示 + 来源徽章（RDAP 蓝 / CNNIC 橙）+ 未注册灰徽章（"No matching record"）+ WHOIS 文本双模式渲染
- 🚀 凭证环境拆分：原「私有云环境」子标签更名为 **「私有云测试环境」**，新增 **「私有云生产环境」** 子标签（数据为空，待录入）；`CRED_ENVS` 扩展为 8 环境
- 📦 数据核对：库内无 `env='私有云环境'` 存量记录（101 条凭证分布于其余 6 环境），无需数据迁移

### v2.7 (2026-08-25)
- 🚀 服务凭证管理「操作」列新增 **复制** 按钮（位于 编辑 / 删除 之间，全员可见）
- ✨ 点击「复制」→ 打开「复制为新凭证」模态框，自动预填源行全部字段（业务用途/业务名称/服务供应商/应用类型/版本/内网外网地址与端口/账号），仅需修改差异字段即可保存为新凭证
- ✨ **业务用途**自动加 `-副本` 后缀便于识别复制来源；**业务名称**保持原值（不加后缀，用户自行决定是否改名）；**密码强制清空**（需重设，不复制原密码，避免凭据复用）；环境默认取当前列表过滤环境
- 🎨 操作列列宽 6rem → 9rem，按钮 `px-2` → `px-1.5`、`gap-1` → `gap-0.5`，编辑/复制/删除三按钮无横向滚动全部可见
- 🎨 表格所有数据列 `align-top` → `align-middle`，"-"占位与多行 URL 视觉垂直居中对齐（消除行高忽高忽低）
- 🎨 业务用途徽章加 `max-w-full truncate` + `title`，超长文本（如「九毛九_嘿菜哈信么mysql」）不再溢出到业务名称列；鼠标悬停查看完整文本
- 🛠 纯前端实现（复用现有新增/编辑模态框与保存逻辑），零后端改动；数据取自 `window._credLastItems` 页面缓存，无额外 API 调用

### v2.6 (2026-08-20)
- 🚀 发版管理分组新增 **发版修复记录** 子标签（参照《2026 年全年云效新发版工单数据汇总》工单重复发版原因汇总表结构）
- ✨ 新表 `release_fix_records`：序号/发布时间/星期/迭代日重复发版/技术线/重复发布工单/工单链接/重复发布服务/重复发布类型/重复发布原因（双模式自动建表）
- ✨ 多条件筛选（关键词/技术线/发版类型/星期/日期范围）+ 统计卡片 + Excel 导入/导出/模板三件套（中文表头映射）
- ✨ 新增/编辑弹窗：选日期自动带出星期；工单标题超链接可点击跳转；服务/原因支持多行
- ✨ 新增 9 个 API：`/api/fix-records` CRUD + filters + import/export/template
- ✨ 表格**按发布时间升序**排列（最早在前）；序号按显示位置自动生成（连续 1,2,3...，删除/筛选后自动重排）；新增时库内 `seq_no` 自动取 max+1
- ✨ UI 优化：星期/技术线改为下拉选择（周一~周日、前端/后端）；表格关键列不换行
- 📦 已从文档导入 47 条生产数据（46 条含工单链接，1 条修正脏值）
- 🐛 修复 K8s 部署下 PING/路由查询/MTR路由 报「command not found」：`Dockerfile` 新增 `iputils-ping` / `traceroute` / `mtr` 包；`k8s/deployment.yaml` 容器 `securityContext.capabilities` 增加 `NET_RAW` + `NET_ADMIN`（ICMP raw socket 需要）
- 🐛 修复 PING 检测 500 / 不可达：`result` 字段初始化 + 正则兼容 `rtt`/`round-trip` 双格式
- 🐛 修复 MTR 报告字段兼容：mtr 0.86~0.95+ 字段名（`Loss%`/`Sent`/`Snt`/小写变体）统一归一化
- ✨ 运维小工具「批量检测」分组新增 **批量PING检测**（`POST /api/utils/batch-ping`，多行输入/10 线程并发/上限 50/防 SSRF）
- 🎨 服务凭证管理弹窗下拉控件统一改为自定义 trigger + 分页搜索面板：**业务用途**（顶部筛选 + 弹窗内）、**业务名称**（弹窗内）、**环境**（弹窗内，含搜索/分页/必填校验）——解决浏览器原生 `<select>` 弹层方向不受控、遮挡表单字段问题
- 🎨 **发版管理 4 子标签 + 域名管理下拉全部统一为自定义 trigger + 下拉面板**（新增泛化组件 `bindDdlPanel`，一次绑定任意下拉）：蓝鲸发版参数（筛选环境/弹窗服务环境）、云效创建变更单（筛选环境/弹窗环境）、云效研发流程（筛选环境/弹窗环境）、发版修复记录（筛选技术线/类型/星期 + 弹窗星期/迭代日/类型/技术线）、域名管理（筛选大区/类型/环境 + 弹窗类型/环境/证书进度）——全部支持搜索/分页/「全部」置顶，弹层方向可控、不遮挡表单字段

### v2.5 (2026-08-19)
- 🚀 运维小工具「计算换算」分组新增 **科学计算器**（纯前端手写表达式解析器，零后端改动）
- ✨ 支持四则运算/括号/幂（右结合）/阶乘/百分号/平方/正负号、科学函数（sin/cos/tan/asin/acos/atan/log/ln/√/1-x/abs）、常量 π/e、隐式乘法（2π、2(3+4)）
- ✨ 角度/弧度切换（DEG/RAD）、实时结果预览、浮点误差收敛（0.1+0.2=0.3）、友好错误提示（除零/定义域/括号不匹配）
- ✨ 计算历史（localStorage 最近 20 条，点击回填/一键清空）+ 物理键盘输入（Enter 计算 / Backspace 退格 / Esc 清空）
- 🐛 修复 SQLite 开发模式登录 500 错误（`sqlite3.Row` 无 `.get()` 方法，MySQL 模式不受影响）

### v2.4 (2026-08-11)
- 🚀 运维小工具新增 **生成器**（密码/密码短语/用户名 三合一 Tab 页）和 **生成器历史记录**（localStorage 最近 20 条）
- 🔐 密码生成用 `crypto.getRandomValues`（密码学安全），必填字符（数字/符号最少）+ Fisher-Yates 洗牌；易混淆字符移除 `0OoIl1L|$&*`
- ✨ 密码短语/用户名基于内置 5000 常用词库（Google 10000 常用词过滤敏感词）

### v2.3 (2026-08-10)
- 🚀 运维小工具新增 **文本比较**（LCS 逐行 diff，支持粘贴/上传/忽略空白/忽略大小写/仅显差异）和 **文本去重**（支持换行/逗号/分号/Tab/空格/自定义分隔符 + 忽略大小写/排序/过滤空项）
- ✨ 两个工具纯前端实现（无 API 请求）；文本比较支持 A⇄B 对调、复制差异；去重展示移除项明细

### v2.2 (2026-08-10)
- 🚀 **新增「运维小工具」模块**（侧边栏可展开，10 个子标签）：CIDR / 时间戳 / JSON / 编解码哈希 / Webhook / 批量端口 / HTTP健康 / 证书批量到期监控 / K8s Yaml检测 / Curl调试
- 🔒 安全：curl/webhook/http 防 SSRF（仅 http(s) + 内网拦截）；curl 参数白名单
- ✨ 新增 `opsutils.py` 模块 + `utils` 权限（用户管理可配置）+ 依赖 `pyyaml`

### v2.1 (2026-08-10)
- 🚀 网络工具新增 **Whois 查询**（RDAP 公共 API）和 **SSL 检测**（证书信息 + TLS 协议矩阵）2 个子工具（共 9 个）
- ✨ Whois/SSL 使用「仅格式校验」模式：允许查询公司内网解析的私有域名（运维刚需），RDAP 查公共注册库不触达目标主机

### v2.0 (2026-08-10)
- 🚀 **新增「网络工具」模块**（侧边栏可展开，7 个子标签）：IP查询 / PING检测 / TCPing / DNS查询 / 路由查询 / MTR路由 / CDN查询
- 🔒 安全设计：内网/回环 IP 黑名单（防 SSRF）、subprocess 强制超时、shell=False
- 🌐 全部工具跨平台（Windows `ping -n`/`tracert`/`pathping`；macOS/Linux `ping -c`/`traceroute`/`mtr`）
- ✨ 新增 `nettools.py` 模块 + `nettools` 权限（用户管理可配置）+ 依赖 `dnspython`
- ✨ IP 查询走第三方免费 API（ip-api.com）；CDN 识别 = CNAME 特征规则库 + ASN 归属库

### v1.5 (2026-08-07)
- 🎨 服务凭证新增 **「服务供应商」列**（位于业务名称后），删除「服务连接地址」列
- 🎨 地址列改为**固定宽度 18rem + 自动换行**（`break-all`），完整展示不再被截断
- 🎨 **业务名称**搜索框改为 `<input list="datalist">` 下拉搜索（可输入可选择已有），参考蓝鲸发版参数的下拉选择体验
- ✨ 新增 `service_credentials.service_provider` 字段（数据库双模式 ALTER 兼容）
- ✨ 新增 `/api/credential-service-names` 和 `/api/credential-providers` 两个 API（用于 datalist 自动补全）
- 🐛 修复编辑按钮失效的根因：域名弹窗 domFormModal 缺 `</div>` 嵌套，导致 credFormModal 等被嵌套在 display:none 父级里（lxml 验证）

### v1.6 (2026-08-17)
- 🎨 服务凭证新增 **「业务用途」列**（表格第一列，彩色徽章）：预设 5 类（点餐业务/会员业务/外卖业务/供应链/通用服务）+ 自定义输入
- 🎨 **🎨 颜色按钮**（仅管理员）：弹窗内为每个业务用途配置颜色（`input type=color` 选色，保存即时生效）
- ✨ 新增 `service_credentials.business_purpose` 字段（默认 '通用服务'，双模式 ALTER 兼容，不动现有数据）
- ✨ 新增 `cred_business_colors` 表（purpose/color 颜色映射）
- ✨ 新增 API：`GET /api/credentials/business-purposes`（用途+颜色）、`PUT /api/credentials/business-purposes/colors`（改色）
- ✨ 凭证列表支持 `?purpose=` 筛选；导出/模板/导入均支持「业务用途」列（导入缺省 '通用服务'）

### v1.4 (2026-08-07)
- 🎨 服务凭证管理 **6 环境子标签移到左侧侧边栏**（与域名管理一致的展开式菜单），页面顶部不再有切换按钮
- 🎨 筛选区拆为 **业务名称 + 关键词** 两个独立搜索框（前者匹配 service_name，后者匹配地址/账号/备注）
- 🐛 修复服务凭证改造导致的 `get_credentials` 函数签名漏加 `env` 参数 → 500 错误
- 🐛 修复 LDAP 服务中断（服务器进程挂掉）的问题，重启后 zhouyicheng 等 LDAP 账号恢复

### v1.3 (2026-08-07)
- 🚀 **服务凭证管理重构为 6 环境子标签**（电信开发/南沙生产/预生产/国内生产/新加坡生产/北美生产）
- 🔐 **密码 AES-256 加密存储**（Fernet），列表脱敏显示、导出脱敏、导入跳过密码列
- ✨ 新增 `crypto.py` 加密模块 + `CRED_SECRET_KEY` 环境变量
- ✨ Excel 导入自动映射 6 子表 → 6 环境（字段模糊匹配），端口内外网保持一致
- ✨ 凭证 API 支持 env 筛选 + 新增 `/api/credential-envs`

### v1.2 (2026-08-07)
- 🚀 **接入公司 LDAP 单点登录**：本地账号 + LDAP 账号双认证源
- 🚀 LDAP 用户首次登录自动开通（JIT），**默认仅发版管理权限**，显示名自动同步
- 🚀 users 表新增 `auth_source` 字段（local/ldap），用户管理页显示认证方式
- ✨ LDAP 配置走 `.env`（LDAP_* 系列），AuthFilter 支持 openldap / AD 两种格式
- ✨ LDAP 密码不落库；LDAP 服务器异常不影响本地账号登录

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

_最后更新：2026-09-01（v2.11.1 登录页飘动动画优化）_
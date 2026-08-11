# 蓝鲸云效运维工具箱

> 基于 Flask + MySQL 8.0（兼容 SQLite）的内部运维工具集，统一管理发版参数、CI/CD 配置、服务凭证、域名及 SSL 证书。

---

## 一、项目简介

本项目把分散在多个 Excel 表格中的运维参数集中到 Web 端，支持可视化筛选、批量复制、导入导出。目前包含 **发版管理**（3 个子标签）、**服务凭证管理**、**域名管理**，以及管理员专属的**用户管理**模块，带完整的 **SHA-256 本地认证 + 公司 LDAP 双认证源**。

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

### 5.5 运维小工具（10 个子标签）

侧边栏「运维小工具」可展开，下挂 **10 个子工具**（权限 `utils`，可在用户管理配置）：

| 子工具 | 说明 | 技术实现 |
|--------|------|---------|
| CIDR 子网计算器 | 网络/广播/可用主机/掩码计算 | Python `ipaddress` |
| 时间戳换算 | Unix 时间戳 ⇄ 人类时间（双向、时区可选） | Python datetime |
| JSON 格式化 | 美化/压缩/语法校验 | Python json |
| 编解码/哈希 | Base64/URL 编解码 + MD5/SHA1/256/512 | Python base64/hashlib |
| Webhook 测试 | 向任意 URL 发送测试请求看响应 | urllib + 防 SSRF 校验 |
| 批量端口连通检查 | 表格批量 TCPing（最多 50 条） | 复用 nettools.tcping |
| HTTP 健康检查 | URL 状态码/耗时/响应头/返回体 | urllib |
| 证书批量到期监控 | 批量 SSL 证书剩余天数（最多 100 条） | 复用 nettools.ssl_inspect |
| K8s Yaml 检测 | YAML 语法 + 资源必填字段/规范检查（多文档） | pyyaml |
| Curl 请求调试 | 粘贴 curl 命令执行看响应 | 安全重组（仅 http/https + 参数白名单） |
| 文本比较 | 逐行 Diff 对比（粘贴/上传，忽略空白/大小写） | 纯前端 LCS 算法 |
| 文本去重 | 按分隔符（换行/逗号/分号/Tab/自定义）去重 | 纯前端 Set 去重 |
| 生成器 | 密码 / 密码短语 / 用户名 三合一 | 纯前端 crypto 安全随机 + 内置 5000 词库 |
| 生成器历史记录 | 弹窗式（最近 20 条，localStorage） | 纯前端，集成在生成器页面右上角 |

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

## 六、数据库设计（6 张表）

### `service_params`
发版参数管理：id, business_module, service_name, create_change_params, run_devflow_params, env, created_at, updated_at

### `ci_orders`
云效创建变更单：id, delivery_service, env, branch, repo_sn, created_at, updated_at

### `ci_devflow`
云效运行研发流程：id, delivery_service, env, wf_sn, stage_sn, created_at, updated_at

### `service_credentials`
服务凭证（6 环境统一表）：id, **env**, service_name(业务名称), **service_provider(服务供应商)**, **app_type, version**, username(账号), **password(加密存储)**, internal_url, internal_port, external_url, external_port, notes, created_at, updated_at

### `domains`
域名管理：id, root_domain, region, service_name, domain_name, domain_type, env, cert_progress, cert_expiry, notes, created_at, updated_at

### `users`
用户认证：id, username, password_hash (SHA-256), display_name, permissions, is_active, **auth_source (local/ldap)**, created_at

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

_最后更新：2026-08-07（v1.3 凭证模块）_
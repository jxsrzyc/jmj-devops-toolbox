#!/usr/bin/env python3
"""运维小工具模块 - 纯工具函数集

包含：CIDR 计算 / 时间戳换算 / JSON 格式化 / 编解码哈希 / Webhook 测试 /
批量端口检查 / HTTP 健康检查 / 证书批量到期监控 / K8s Yaml 检测 / Curl 请求调试

安全设计：
- curl/webhook/http 请求仅允许 http(s) 协议，禁止内网/回环目标（防 SSRF）
- curl 命令解析后重组执行，禁止 shell 注入
"""
import os
import re
import json
import time
import base64
import hashlib
import ipaddress
import urllib.parse
import subprocess
from datetime import datetime, timezone, timedelta
from urllib.request import urlopen, Request

# ==================== 通用安全 ====================

URL_RE = re.compile(r'^(https?)://', re.I)
CURL_URL_RE = re.compile(r'https?://[^\s\'"<>]+', re.I)


def _is_internal_ip(ip):
    try:
        addr = ipaddress.ip_address(ip)
        return (addr.is_private or addr.is_loopback or addr.is_link_local
                or addr.is_multicast or addr.is_reserved or addr.is_unspecified)
    except ValueError:
        return False


def _validate_url(url):
    """校验 URL 协议 + 非内网目标。返回 (ok, message, normalized)"""
    url = (url or "").strip()
    if not URL_RE.match(url):
        return False, "仅支持 http/https 协议", ""
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname
    if not host:
        return False, "URL 不合法（缺少主机名）", ""
    # 主机名直接是 IP
    try:
        ip = ipaddress.ip_address(host)
        if _is_internal_ip(host):
            return False, "禁止访问内网/回环地址", ""
        return True, "", url
    except ValueError:
        pass
    # 域名：解析后校验
    import socket
    try:
        infos = socket.getaddrinfo(host, None)
        for info in infos:
            if _is_internal_ip(info[4][0]):
                return False, "该域名解析到内网地址，禁止访问", ""
    except Exception:
        return False, "域名解析失败", ""
    return True, "", url


def _http_request(url, method="GET", headers=None, body=None, timeout=10):
    """安全发送 HTTP 请求。返回 dict（状态码/响应头/响应体/耗时/错误）"""
    t0 = time.time()
    ok, msg, url = _validate_url(url)
    if not ok:
        return {"error": msg}
    try:
        data = None
        if body is not None:
            data = body.encode() if isinstance(body, str) else body
        req = Request(url, data=data, headers=headers or {}, method=method.upper())
        with urlopen(req, timeout=timeout) as resp:
            resp_body = resp.read().decode("utf-8", errors="replace")
            cost = round((time.time() - t0) * 1000, 2)
            return {
                "status": resp.status,
                "headers": dict(resp.headers.items()),
                "body": resp_body[:20000],
                "cost_ms": cost,
                "final_url": resp.geturl(),
            }
    except Exception as e:
        cost = round((time.time() - t0) * 1000, 2)
        return {"error": str(e), "cost_ms": cost}


# ==================== 1. CIDR 子网计算器 ====================

def cidr_calc(cidr):
    """CIDR 计算：网络地址/广播地址/可用主机数/掩码等"""
    cidr = (cidr or "").strip()
    try:
        net = ipaddress.ip_network(cidr, strict=False)
    except ValueError as e:
        return {"code": 1, "message": f"CIDR 格式不合法: {str(e)}"}
    hosts = list(net.hosts())
    return {"code": 0, "data": {
        "network": str(net.network_address),
        "broadcast": str(net.broadcast_address) if net.version == 4 else "-",
        "netmask": str(net.netmask),
        "prefixlen": net.prefixlen,
        "version": f"IPv{net.version}",
        "total_hosts": net.num_addresses,
        "usable_hosts": len(hosts),
        "first_host": str(hosts[0]) if hosts else "-",
        "last_host": str(hosts[-1]) if hosts else "-",
        "wildcard": str(net.hostmask) if net.version == 4 else "-",
    }}


# ==================== 2. 时间戳换算 ====================

def timestamp_convert(value, tz_offset=8):
    """Unix 时间戳 ⇄ 人类时间（支持双向）"""
    value = (value or "").strip()
    tz = timezone(timedelta(hours=tz_offset))
    if not value:
        return {"code": 1, "message": "请输入时间戳或日期时间"}
    # 尝试数字时间戳（秒/毫秒/微秒）
    if value.isdigit():
        ts = int(value)
        if ts > 10 ** 12:      # 微秒
            ts = ts / 1_000_000
        elif ts > 10 ** 10:    # 毫秒
            ts = ts / 1000
        dt = datetime.fromtimestamp(ts, tz)
        return {"code": 0, "data": {
            "type": "timestamp → datetime",
            "datetime": dt.strftime("%Y-%m-%d %H:%M:%S"),
            "tz": f"UTC{tz_offset:+d}",
            "weekday": "星期" + "一二三四五六日"[dt.weekday()],
            "iso": dt.isoformat(),
        }}
    # 尝试人类时间 → 时间戳
    try:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S.%f"):
            try:
                dt = datetime.strptime(value, fmt).replace(tzinfo=tz)
                break
            except ValueError:
                continue
        else:
            return {"code": 1, "message": "时间格式不识别，支持: 2026-08-10 12:00:00"}
        ts = int(dt.timestamp())
        return {"code": 0, "data": {
            "type": "datetime → timestamp",
            "timestamp_sec": ts,
            "timestamp_ms": ts * 1000,
            "tz": f"UTC{tz_offset:+d}",
        }}
    except Exception as e:
        return {"code": 1, "message": f"解析失败: {str(e)}"}


# ==================== 3. JSON 格式化 ====================

def json_format(text, indent=2):
    """JSON 美化/压缩/校验"""
    text = (text or "").strip()
    if not text:
        return {"code": 1, "message": "请输入 JSON 内容"}
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return {"code": 1, "message": f"JSON 语法错误: 第 {e.lineno} 行 第 {e.colno} 列 {e.msg}"}
    pretty = json.dumps(data, ensure_ascii=False, indent=indent)
    compact = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return {"code": 0, "data": {"pretty": pretty, "compact": compact, "type": type(data).__name__}}


# ==================== 4. 编解码 / 哈希 ====================

def encode_hash(text, action="base64_encode", algo="sha256"):
    """编解码与哈希（action: base64_encode/base64_decode/url_encode/url_decode/md5/sha1/sha256/sha512）"""
    text = (text or "")
    if not text:
        return {"code": 1, "message": "请输入内容"}
    try:
        if action == "base64_encode":
            return {"code": 0, "data": {"result": base64.b64encode(text.encode()).decode()}}
        if action == "base64_decode":
            return {"code": 0, "data": {"result": base64.b64decode(text).decode("utf-8", errors="replace")}}
        if action == "url_encode":
            return {"code": 0, "data": {"result": urllib.parse.quote(text, safe="")}}
        if action == "url_decode":
            return {"code": 0, "data": {"result": urllib.parse.unquote(text)}}
        if action in ("md5", "sha1", "sha256", "sha512"):
            h = hashlib.new(action, text.encode()).hexdigest()
            return {"code": 0, "data": {"result": h, "length": len(h)}}
        return {"code": 1, "message": f"不支持的操作: {action}"}
    except Exception as e:
        return {"code": 1, "message": f"操作失败: {str(e)}"}


# ==================== 5. Webhook 测试 ====================

def webhook_test(url, method="POST", headers=None, body=""):
    """发送 Webhook 测试请求"""
    hdrs = {k: v for k, v in (headers or {}).items() if k and v}
    return {"code": 0, "data": _http_request(url, method=method, headers=hdrs, body=body)}


# ==================== 6. 批量端口连通检查 ====================

def batch_tcping(items):
    """批量 TCP 端口检查。items: [{"host": "x", "port": 80}, ...]"""
    from nettools import tcping, validate_host_fmt
    results = []
    for it in (items or [])[:50]:   # 上限 50 条
        host = (it.get("host") or "").strip()
        try:
            port = int(it.get("port", 80))
        except (TypeError, ValueError):
            port = 80
        if not host or not (1 <= port <= 65535):
            results.append({"host": host, "port": port, "reachable": False, "error": "参数不合法"})
            continue
        r = tcping(host, port, timeout=3)
        if r["code"] == 0:
            d = r["data"]
            results.append({"host": host, "port": port, "reachable": d.get("reachable"),
                            "connect_ms": d.get("connect_ms"), "message": d.get("message", "")})
        else:
            results.append({"host": host, "port": port, "reachable": False, "error": r["message"]})
    return {"code": 0, "data": results}


# ==================== 7. HTTP 健康检查 ====================

def http_health(url, timeout=10):
    """HTTP 健康检查：状态码/耗时/响应头/重定向"""
    return {"code": 0, "data": _http_request(url, method="GET", timeout=timeout)}


# ==================== 7.1 批量 PING 检测 ====================

def batch_ping(items, count=4, timeout=2):
    """批量 PING 检测。items: ["8.8.8.8", "www.baidu.com", ...] 或 [{"host": "..."}, ...]，上限 50 条

    并发执行（ThreadPoolExecutor max_workers=10）避免串行触发网关超时；
    复用 nettools.ping_detect + validate_host（防 SSRF：拒绝内网/回环/私有/多播地址）。
    """
    from nettools import ping_detect, validate_host
    from concurrent.futures import ThreadPoolExecutor, as_completed
    hosts = []
    for it in (items or [])[:50]:
        if isinstance(it, str):
            host = it.strip()
        elif isinstance(it, dict):
            host = (it.get("host") or "").strip()
        else:
            host = ""
        if host:
            hosts.append(host)

    def _one(host):
        # 输入校验（防 SSRF）
        ok, msg, norm = validate_host(host)
        if not ok:
            return {"host": host, "success": False, "error": msg}
        r = ping_detect(norm, count=count, timeout=timeout)
        if r["code"] == 0:
            d = r["data"]
            return {
                "host": norm,
                "success": d.get("success"),
                "loss": d.get("loss"),
                "avg": d.get("avg"),
                "min": d.get("min"),
                "max": d.get("max"),
                "ttl": d.get("ttl"),
                "cost": d.get("cost"),
            }
        return {"host": norm, "success": False, "error": r["message"]}

    results = []
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = {ex.submit(_one, h): h for h in hosts}
        for fut in as_completed(futs):
            try:
                results.append(fut.result())
            except Exception as e:
                results.append({"host": futs[fut], "success": False, "error": str(e)[:120]})
    # 保持输入顺序
    order = {h: i for i, h in enumerate(hosts)}
    results.sort(key=lambda r: order.get(r["host"], 999))
    return {"code": 0, "data": results}


# ==================== 8. 证书批量到期监控 ====================

def cert_monitor(domains):
    """批量检测域名证书到期。domains: ["a.com", ...]（复用 nettools.ssl_inspect）"""
    from nettools import ssl_inspect, validate_host_fmt
    results = []
    for domain in (domains or [])[:100]:   # 上限 100 条
        domain = (domain or "").strip()
        ok, msg, _ = validate_host_fmt(domain)
        if not ok:
            results.append({"domain": domain, "error": msg})
            continue
        r = ssl_inspect(domain, 443)
        if r["code"] != 0:
            results.append({"domain": domain, "error": r["message"]})
            continue
        c = r["data"]["cert"]
        days = None
        if c.get("not_after"):
            try:
                exp = datetime.fromisoformat(c["not_after"].replace("+00:00", ""))
                days = (exp - datetime.utcnow()).days
            except Exception:
                pass
        results.append({"domain": domain, "subject_cn": c.get("subject_cn"),
                        "issuer": c.get("issuer_cn"), "not_after": c.get("not_after"),
                        "days_left": days, "tls": c.get("tls_version_used")})
    return {"code": 0, "data": results}


# ==================== 9. K8s Yaml 检测 ====================

# K8s 必填字段检查（kind → 必填路径，apiVersion/kind/metadata.name 由基础检查统一覆盖）
K8S_REQUIRED = {
    "Deployment": ["spec.template.spec.containers"],
    "StatefulSet": ["spec.template.spec.containers"],
    "DaemonSet": ["spec.template.spec.containers"],
    "Service": ["spec.ports"],
    "Ingress": [],
    "ConfigMap": [],
    "Secret": [],
    "Namespace": [],
    "Pod": ["spec.containers"],
    "Job": ["spec.template.spec.containers"],
    "CronJob": ["spec.jobTemplate.spec.template.spec.containers"],
    "PV": ["spec.capacity"],
    "PVC": ["spec.resources"],
    "HPA": ["spec.scaleTargetRef"],
}


def _get_path(doc, path):
    """按 a.b.c 路径取值"""
    cur = doc
    for key in path.split("."):
        if isinstance(cur, dict) and key in cur:
            cur = cur[key]
        else:
            return None
    return cur


def yaml_check(text):
    """K8s Yaml 检测：YAML 语法 + 多文档 + 资源必填字段 + 常见规范检查"""
    try:
        import yaml
    except ImportError:
        return {"code": 1, "message": "未安装 pyyaml，请 pip install pyyaml"}
    if not (text or "").strip():
        return {"code": 1, "message": "请输入 YAML 内容"}
    try:
        docs = list(yaml.safe_load_all(text))
    except yaml.YAMLError as e:
        return {"code": 1, "message": f"YAML 语法错误: {str(e)}"}

    results = []
    for idx, doc in enumerate(docs, 1):
        if doc is None:
            results.append({"doc": idx, "kind": "(空文档)", "ok": False, "issues": ["空文档，跳过"]})
            continue
        if not isinstance(doc, dict):
            results.append({"doc": idx, "kind": type(doc).__name__, "ok": False,
                            "issues": ["文档不是对象（期望是 K8s 资源定义）"]})
            continue
        kind = doc.get("kind", "")
        api_version = doc.get("apiVersion", "")
        name = ""
        if isinstance(doc.get("metadata"), dict):
            name = doc["metadata"].get("name", "")
        issues = []
        # 基础字段
        if not api_version:
            issues.append("缺少必填字段: apiVersion")
        if not kind:
            issues.append("缺少必填字段: kind")
        if not name:
            issues.append("缺少必填字段: metadata.name")
        # 按 kind 检查必填路径
        for path in K8S_REQUIRED.get(kind, []):
            if path.startswith("metadata.name"):
                continue
            if _get_path(doc, path) is None:
                issues.append(f"缺少必填字段: {path}")
        # 常见规范检查
        if kind in ("Deployment", "StatefulSet", "DaemonSet"):
            if not _get_path(doc, "spec.template.metadata.labels"):
                issues.append("建议: spec.template.metadata.labels 缺失（Pod 标签）")
            if not _get_path(doc, "spec.selector.matchLabels"):
                issues.append("建议: spec.selector.matchLabels 缺失")
            conts = _get_path(doc, "spec.template.spec.containers") or []
            for ci, c in enumerate(conts):
                if isinstance(c, dict) and not c.get("image"):
                    issues.append(f"建议: containers[{ci}] 缺少 image")
        if kind == "Ingress" and not _get_path(doc, "spec.rules"):
            issues.append("建议: spec.rules 缺失（无路由规则）")
        if kind == "Service" and not _get_path(doc, "spec.selector"):
            issues.append("建议: spec.selector 缺失（Service 选择器）")
        results.append({"doc": idx, "kind": kind or "?", "name": name, "ok": not issues, "issues": issues})
    return {"code": 0, "data": {"doc_count": len(results), "results": results}}


# ==================== 10. Curl 请求调试 ====================

def curl_debug(curl_command):
    """解析并执行 curl 命令（安全重组：仅 http/https + 非内网 + 无 shell）"""
    cmd = (curl_command or "").strip()
    if not cmd:
        return {"code": 1, "message": "请输入 curl 命令"}
    if not re.match(r'^curl\s+', cmd, re.I):
        return {"code": 1, "message": "命令必须以 curl 开头"}
    # 提取 URL
    m = CURL_URL_RE.search(cmd)
    if not m:
        return {"code": 1, "message": "未找到 URL"}
    url = m.group(0).rstrip('"\'')
    ok, msg, url = _validate_url(url)
    if not ok:
        return {"code": 1, "message": msg}
    # 重组安全命令：只保留 -X/-H/-d/-k/--data/-u 等无害参数
    import shlex
    safe_args = []
    try:
        tokens = shlex.split(cmd, posix=True)
    except ValueError as e:
        return {"code": 1, "message": f"命令引号不匹配: {str(e)}"}
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t.lower() in ("curl",):
            i += 1
            continue
        if t.lower() in ("-x", "--request"):
            if i + 1 < len(tokens):
                safe_args.extend(["-X", tokens[i + 1]])
                i += 2
                continue
        if t.lower() in ("-h", "--header"):
            if i + 1 < len(tokens):
                safe_args.extend(["-H", tokens[i + 1]])
                i += 2
                continue
        if t.lower() in ("-d", "--data", "--data-raw", "--data-urlencode", "-u", "--user"):
            if i + 1 < len(tokens):
                safe_args.extend([t, tokens[i + 1]])
                i += 2
                continue
        if t.lower() in ("-k", "--insecure", "-s", "--silent", "-i", "--include", "-v", "--verbose", "--compressed", "-L", "--location"):
            safe_args.append(t)
            i += 1
            continue
        # -w/--write-out 带值
        if t.lower() in ("-w", "--write-out"):
            if i + 1 < len(tokens):
                safe_args.extend(["-w", tokens[i + 1].strip('"\'')])
                i += 2
                continue
            return {"code": 1, "message": "-w 缺少输出格式参数"}
        # -o 仅允许 /dev/null（防写文件）
        if t.lower() in ("-o", "--output"):
            if i + 1 < len(tokens) and tokens[i + 1].strip() in ("/dev/null", "NUL"):
                safe_args.extend(["-o", "/dev/null"])
                i += 2
                continue
            return {"code": 1, "message": "-o 仅允许输出到 /dev/null"}
        # -m/--max-time 限时
        if t.lower() in ("-m", "--max-time"):
            if i + 1 < len(tokens) and tokens[i + 1].isdigit():
                safe_args.extend(["-m", tokens[i + 1]])
                i += 2
                continue
            return {"code": 1, "message": "-m 需要数字超时（秒）"}
        # URL token（加入执行参数）
        if CURL_URL_RE.match(t):
            safe_args.append(t)
            i += 1
            continue
        return {"code": 1, "message": f"不支持的参数: {t}（仅允许 -X/-H/-d/-u/-k/-s/-i/-w/-o /dev/null 等）"}
    try:
        proc = subprocess.run(["curl", *safe_args], capture_output=True, text=True, timeout=20, shell=False)
        body = proc.stdout or proc.stderr
        return {"code": 0, "data": {"exit_code": proc.returncode, "output": body[:20000]}}
    except subprocess.TimeoutExpired:
        return {"code": 1, "message": "curl 执行超时（20s）"}
    except FileNotFoundError:
        return {"code": 1, "message": "系统未安装 curl"}
    except Exception as e:
        return {"code": 1, "message": f"执行失败: {str(e)}"}

#!/usr/bin/env python3
import ssl
"""网络工具模块 - 跨平台（Windows / macOS / Linux）

包含：IP查询 / PING检测 / TCPing / DNS查询 / 路由查询 / MTR路由 / CDN查询

安全设计：
- 输入校验：仅允许合法域名/IP，黑名单屏蔽内网/回环地址（防 SSRF）
- 命令执行：subprocess + shell=False + 强制超时
- 所有 API 返回统一 {code, data, message}
"""
import os
import re
import json
import time
import socket
import platform
import subprocess
import ipaddress
from urllib.request import urlopen, Request
from urllib.parse import quote

SYSTEM = platform.system()  # 'Windows' | 'Darwin' | 'Linux'

# ==================== 输入校验（防 SSRF） ====================

DOMAIN_RE = re.compile(r'^(?=.{1,253}$)([a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,63}$')
IPV4_RE = re.compile(r'^\d{1,3}(\.\d{1,3}){3}$')


def _is_internal_ip(ip):
    """判断 IP 是否为内网/回环/链路本地地址"""
    try:
        addr = ipaddress.ip_address(ip)
        return (addr.is_private or addr.is_loopback or addr.is_link_local
                or addr.is_multicast or addr.is_reserved or addr.is_unspecified)
    except ValueError:
        return False


def _is_internal_hostname(host):
    """判断域名是否解析到内网 IP"""
    try:
        infos = socket.getaddrinfo(host, None)
        for info in infos:
            ip = info[4][0]
            if _is_internal_ip(ip):
                return True
    except Exception:
        return False
    return False


def validate_host(host):
    """校验主机名/IP：合法格式 + 非内网。返回 (ok, message, normalized)"""
    host = (host or "").strip().rstrip('.')
    if not host:
        return False, "请输入主机名或 IP", ""
    if len(host) > 253:
        return False, "主机名过长", ""
    # 内网域名/特殊名黑名单
    if host.lower() in ('localhost', 'localhost.localdomain', 'gateway', 'router'):
        return False, "禁止访问本机/内网主机", ""
    # IP 格式
    if IPV4_RE.match(host):
        parts = host.split('.')
        if any(int(p) > 255 for p in parts):
            return False, "IPv4 地址非法（每段 0-255）", ""
        if _is_internal_ip(host):
            return False, "禁止访问内网/回环 IP", ""
        return True, "", host
    # 域名格式
    if DOMAIN_RE.match(host):
        if _is_internal_hostname(host):
            return False, "该域名解析到内网地址，禁止访问", ""
        return True, "", host
    # IPv6 简单校验
    try:
        addr = ipaddress.ip_address(host)
        if _is_internal_ip(host):
            return False, "禁止访问内网/回环 IP", ""
        return True, "", host
    except ValueError:
        return False, "格式不合法：请输入域名或 IP", ""


def validate_host_fmt(host):
    """仅校验主机名/IP 格式（不拦截内网解析）。
    用于 Whois（RDAP 查公共注册库，不连接目标主机）和 SSL 检测
    （运维常查公司内网/私有域名的证书），内网域名是正常使用场景。
    """
    host = (host or "").strip().rstrip('.')
    if not host:
        return False, "请输入主机名或 IP", ""
    if len(host) > 253:
        return False, "主机名过长", ""
    if host.lower() in ('localhost', 'localhost.localdomain'):
        return False, "禁止访问本机", ""
    if IPV4_RE.match(host):
        parts = host.split('.')
        if any(int(p) > 255 for p in parts):
            return False, "IPv4 地址非法（每段 0-255）", ""
        return True, "", host
    if DOMAIN_RE.match(host):
        return True, "", host
    try:
        ipaddress.ip_address(host)
        return True, "", host
    except ValueError:
        return False, "格式不合法：请输入域名或 IP", ""


def _run_cmd(cmd, timeout=15):
    """安全执行系统命令（shell=False + 超时）。返回 (ok, stdout, stderr)"""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout, shell=False)
        return proc.returncode == 0, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return False, "", f"命令执行超时（>{timeout}s）"
    except FileNotFoundError:
        return False, "", f"命令不存在: {cmd[0]}（当前系统: {SYSTEM}）"
    except Exception as e:
        return False, "", str(e)


# ==================== 1. IP 查询（第三方免费 API） ====================

IP_API_URL = "http://ip-api.com/json/{ip}?lang=zh-CN&fields=status,message,country,regionName,city,isp,org,as,asname,lat,lon,timezone,query,reverse,mobile,proxy,hosting"


def ip_lookup(target):
    """查询 IP 归属地（第三方免费 API ip-api.com）"""
    # 支持输入 IP 或域名（域名先解析成 IP）
    ip = target.strip()
    if IPV4_RE.match(ip):
        if _is_internal_ip(ip):
            return {"code": 1, "message": "禁止查询内网/回环 IP"}
    elif DOMAIN_RE.match(ip) or (':' in ip):
        try:
            ip = socket.gethostbyname(ip)
        except Exception:
            return {"code": 1, "message": f"无法解析域名: {target}"}
        if _is_internal_ip(ip):
            return {"code": 1, "message": "该域名解析到内网地址"}
    else:
        return {"code": 1, "message": "请输入合法 IP 或域名"}
    try:
        url = IP_API_URL.format(ip=ip)
        req = Request(url, headers={"User-Agent": "Mozilla/5.0 (ops-toolbox)"})
        with urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
        if data.get("status") != "success":
            return {"code": 1, "message": data.get("message", "查询失败")}
        return {"code": 0, "data": {
            "ip": data.get("query", ip),
            "country": data.get("country", ""),
            "region": data.get("regionName", ""),
            "city": data.get("city", ""),
            "isp": data.get("isp", ""),
            "org": data.get("org", ""),
            "as": data.get("as", ""),
            "asname": data.get("asname", ""),
            "lat": data.get("lat"),
            "lon": data.get("lon"),
            "timezone": data.get("timezone", ""),
            "reverse": data.get("reverse", ""),
            "mobile": data.get("mobile"),
            "proxy": data.get("proxy"),
            "hosting": data.get("hosting"),
        }}
    except Exception as e:
        return {"code": 1, "message": f"IP 归属查询失败: {str(e)}"}


# ==================== 2. PING 检测 ====================

def ping_detect(host, count=4, timeout=5):
    """ICMP 连通性检测（跨平台命令，兼容 macOS/Linux/Windows 输出格式）"""
    if SYSTEM == "Windows":
        cmd = ["ping", "-n", str(count), "-w", str(timeout * 1000), host]
    else:
        cmd = ["ping", "-c", str(count), "-W", str(timeout), host]
    t0 = time.time()
    ok, stdout, stderr = _run_cmd(cmd, timeout=(timeout * count) + 15)
    cost = round(time.time() - t0, 2)
    if not ok and "命令不存在" in stderr:
        return {"code": 1, "message": stderr}
    text = stdout or stderr or ""
    result = {"host": host, "output": text, "cost": cost, "samples": []}

    # 逐行延迟: "time=95.8 ms" / "time<1ms" / "时间=95ms"(Windows中文) / "95.8 ms"
    time_re = re.compile(r'time[=<]\s*(\d+\.?\d*)\s*ms', re.I)
    result["samples"] = [float(m) for m in time_re.findall(text)]

    # 统计行: "round-trip min/avg/max/stddev = 95.810/150.745/203.742/39.611 ms"
    stat_re = re.search(r'(?:round-trip|最短|平均|最长)[^=]*=\s*([\d.]+)/([\d.]+)/([\d.]+)', text, re.I)
    if stat_re:
        result["min"] = float(stat_re.group(1))
        result["avg"] = float(stat_re.group(2))
        result["max"] = float(stat_re.group(3))

    # 丢包: "0.0% packet loss" / "丢失 = 0 (0% 丢失)" (Windows中文) / "100% packet loss"
    loss = None
    loss_en = re.search(r'(\d+(?:\.\d+)?)%\s*packet loss', text, re.I)
    loss_zh = re.search(r'(\d+(?:\.\d+)?)\s*%?\s*(?:丢失|loss)', text, re.I)
    if loss_en:
        loss = float(loss_en.group(1))
    elif loss_zh:
        loss = float(loss_zh.group(1))
    if loss is None:
        # 无丢包行：如果统计行存在则视为 0，否则 100
        loss = 0.0 if stat_re else 100.0
    result["loss"] = loss

    # TTL（逐行或统计）
    ttl_re = re.search(r'ttl[=:](\d+)', text, re.I)
    result["ttl"] = int(ttl_re.group(1)) if ttl_re else None

    # 可达性：有统计行且丢包<100 视为可达
    result["success"] = bool(stat_re) and loss < 100
    if result["avg"] is None and result["samples"]:
        result["min"] = min(result["samples"])
        result["max"] = max(result["samples"])
        result["avg"] = round(sum(result["samples"]) / len(result["samples"]), 2)
    return {"code": 0, "data": result}


# ==================== 3. TCPing ====================

def tcping(host, port, timeout=3):
    """TCP 端口连通性测试（纯 socket，跨平台）"""
    if not (1 <= int(port) <= 65535):
        return {"code": 1, "message": "端口范围 1-65535"}
    t0 = time.time()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((host, int(port)))
        cost = round((time.time() - t0) * 1000, 2)
        sock.close()
        return {"code": 0, "data": {"host": host, "port": int(port),
                                    "reachable": True, "connect_ms": cost}}
    except socket.timeout:
        return {"code": 0, "data": {"host": host, "port": int(port),
                                    "reachable": False, "connect_ms": None,
                                    "message": f"连接超时（{timeout}s）"}}
    except socket.gaierror:
        return {"code": 1, "message": f"无法解析主机名: {host}"}
    except ConnectionRefusedError:
        return {"code": 0, "data": {"host": host, "port": int(port),
                                    "reachable": False, "connect_ms": None,
                                    "message": "连接被拒绝（端口未监听）"}}
    except OSError as e:
        return {"code": 0, "data": {"host": host, "port": int(port),
                                    "reachable": False, "connect_ms": None,
                                    "message": str(e)}}


# ==================== 4. DNS 查询 ====================

PUBLIC_DNS = ["8.8.8.8", "1.1.1.1", "114.114.114.114", "223.5.5.5", "192.168.0.246", "172.18.90.50"]
DNS_TYPES = ["A", "AAAA", "CNAME", "MX", "NS", "TXT", "SOA", "PTR", "SRV", "CAA"]


def dns_query(host, record_type="A", dns_server=None, timeout=5):
    """DNS 记录查询（dnspython，多公共 DNS）"""
    import dns.resolver
    import dns.rdatatype
    record_type = (record_type or "A").upper()
    if record_type not in DNS_TYPES:
        return {"code": 1, "message": f"不支持的类型: {record_type}（支持: {','.join(DNS_TYPES)}）"}
    servers = [dns_server] if dns_server else PUBLIC_DNS
    results = []
    for ns in servers:
        try:
            resolver = dns.resolver.Resolver(configure=False)
            resolver.nameservers = [ns]
            resolver.timeout = timeout
            resolver.lifetime = timeout
            answers = resolver.resolve(host, record_type)
            records = []
            for ans in answers:
                if record_type == "A":
                    records.append(str(ans.address))
                elif record_type == "AAAA":
                    records.append(str(ans.address))
                elif record_type == "CNAME":
                    records.append(str(ans.target).rstrip('.'))
                elif record_type == "MX":
                    records.append(f"{ans.preference} {str(ans.exchange).rstrip('.')}")
                elif record_type == "NS":
                    records.append(str(ans.target).rstrip('.'))
                elif record_type == "TXT":
                    records.append(''.join(s.decode() if isinstance(s, bytes) else s for s in ans.strings))
                elif record_type == "SOA":
                    m = ans
                    records.append(f"{m.mname} {m.rname} serial={m.serial} refresh={m.refresh} retry={m.retry} expire={m.expire} minimum={m.minimum}")
                elif record_type == "PTR":
                    records.append(str(ans.target).rstrip('.'))
                elif record_type == "SRV":
                    records.append(f"{ans.priority} {ans.weight} {ans.port} {str(ans.target).rstrip('.')}")
                elif record_type == "CAA":
                    records.append(f"{ans.flags} {ans.tag} {ans.value}")
            results.append({"server": ns, "status": "ok", "records": records,
                            "ttl": answers.rrset.ttl if answers.rrset else None})
        except Exception as e:
            msg = str(e)
            # 翻译常见 dnspython 异常
            if "REFUSED" in msg:
                msg = "该 DNS 服务器主动拒绝查询（REFUSED，可能是 ACL 限制 / 未配置该域名 zone / 仅作转发器）"
            elif "NXDOMAIN" in msg:
                msg = "域名不存在（NXDOMAIN）"
            elif "No nameservers" in msg or "NoNameservers" in msg:
                msg = "所有 DNS 服务器均查询失败"
            elif "timeout" in msg.lower() or "Timeout" in msg:
                msg = f"查询超时（{timeout}s），DNS 服务器不可达"
            elif "NoAnswer" in msg:
                msg = f"DNS 服务器返回空 Answer（该类型无记录）"
            results.append({"server": ns, "status": "error", "message": msg})
    return {"code": 0, "data": {"host": host, "type": record_type, "results": results}}


# ==================== 5. 路由查询（Traceroute） ====================

def route_trace(host, max_hops=30, timeout=5):
    """路由追踪（跨平台: Windows tracert / macOS·Linux traceroute）"""
    if SYSTEM == "Windows":
        cmd = ["tracert", "-d", "-h", str(max_hops), "-w", str(timeout * 1000), host]
    else:
        cmd = ["traceroute", "-m", str(max_hops), "-q", "1", "-w", str(timeout), host]
    ok, stdout, stderr = _run_cmd(cmd, timeout=(timeout * max_hops) + 15)
    if not ok and "命令不存在" in stderr:
        return {"code": 1, "message": stderr}
    return {"code": 0, "data": {"host": host, "output": stdout or stderr}}


# ==================== 6. MTR 路由（去程丢包/延迟） ====================

def mtr_trace(host, count=10, timeout=5):
    """MTR 路由分析（macOS/Linux: mtr -j；Windows: pathping 降级）"""
    if SYSTEM == "Windows":
        # Windows 无原生 mtr，用 pathping 降级（输出逐跳统计）
        cmd = ["pathping", "-n", "-q", "1", "-h", "30", host]
        ok, stdout, stderr = _run_cmd(cmd, timeout=120)
        return {"code": 0, "data": {"host": host, "mode": "pathping (Windows 降级)",
                                    "output": stdout or stderr}}
    # macOS/Linux: mtr --report --json
    cmd = ["mtr", "--report", "-c", str(count), "-j", host]
    ok, stdout, stderr = _run_cmd(cmd, timeout=120)
    if not ok and "命令不存在" in stderr:
        return {"code": 1, "message": "当前系统未安装 mtr（macOS: brew install mtr；Linux: yum/apt install mtr）"}
    try:
        data = json.loads(stdout)
        return {"code": 0, "data": {"host": host, "mode": "mtr", "report": data}}
    except Exception:
        return {"code": 0, "data": {"host": host, "mode": "mtr (raw)",
                                    "output": stdout or stderr}}


# ==================== 7. CDN 查询（特征规则库 + ASN 归属） ====================

# CDN 特征规则库（CNAME 后缀特征）
CDN_CNAME_RULES = [
    ("Cloudflare", ["cloudflare.com", "cloudflare.net"]),
    ("CloudFront (AWS)", ["cloudfront.net", "amazonaws.com"]),
    ("Akamai", ["akamaized.net", "akamai.net", "akamaiedge.net", "edgesuite.net"]),
    ("Fastly", ["fastly.net", "fastlylb.net"]),
    ("阿里云CDN", ["aliyuncs.com", "alikunlun.com", "kunlun.com", "kunlunar.com"]),
    ("腾讯云CDN", ["tencentcs.com", "myqcloud.com", "tcdn.qq.com"]),
    ("腾讯DNSPod边缘加速", ["dnse2.com", "dnsv1.com"]),  # DNSPod Enterprise Optimization 边缘加速
    ("华为云CDN", ["hacdn.net", "huaweicloud.com"]),
    ("网宿CDN", ["wscdns.com", "chinacache.net", "cdnnetworks.com"]),
    ("七牛云CDN", ["qiniudns.com", "qiniucdn.com"]),
    ("百度云加速", ["dnsv1.com.cn", "bdydns.com"]),
    ("Azure CDN", ["azureedge.net", "azurefd.net", "trafficmanager.net"]),
    ("金山云", ["ksyun.com", "ksyuncs.com"]),
    ("UCloud", ["ucloud.com.cn", "ufileos.com"]),
    ("又拍云", ["upaiyun.com"]),
    ("网宿(ChinaNetCenter)", ["cnc-cloud.cn", "chinanetcenter.com"]),
]

# CDN ASN 特征规则库
CDN_ASN_RULES = [
    ("Cloudflare", ["AS13335", "AS209242"]),
    ("CloudFront (AWS)", ["AS16509", "AS14618", "AS13076"]),
    ("Akamai", ["AS20940", "AS16625", "AS18680", "AS34164"]),
    ("Fastly", ["AS54113"]),
    ("阿里云CDN", ["AS45102", "AS37963"]),
    ("腾讯云CDN", ["AS132203", "AS45090"]),
    ("华为云CDN", ["AS136907", "AS55990"]),
    ("Azure CDN", ["AS8075", "AS8074"]),
    ("七牛云", ["AS45543"]),
    ("UCloud", ["AS135377"]),
    ("网宿", ["AS7506", "AS139646"]),
    ("百度云加速", ["AS140911"]),
    ("金山云", ["AS136038"]),
]


def _detect_cdn_by_cname(host):
    """通过 CNAME 特征识别 CDN。返回 (hit_or_none, all_cname_chain)"""
    all_chain = []
    try:
        import dns.resolver
        resolver = dns.resolver.Resolver(configure=False)
        resolver.nameservers = ["8.8.8.8", "1.1.1.1"]
        resolver.timeout = 5
        resolver.lifetime = 5
        # 首跳 CNAME
        try:
            answers = resolver.resolve(host, "CNAME")
            for ans in answers:
                all_chain.append(str(ans.target).lower().rstrip('.'))
        except Exception:
            pass
        # 追链：解析 CNAME 指向的域名再查
        cur = host
        for _ in range(8):
            try:
                answers = resolver.resolve(cur, "CNAME")
                nxt = str(answers[0].target).lower().rstrip('.')
                if nxt and nxt not in all_chain:
                    all_chain.append(nxt)
                cur = nxt
            except Exception:
                break
        # 规则匹配
        for cname in all_chain:
            for name, patterns in CDN_CNAME_RULES:
                for pat in patterns:
                    if pat in cname:
                        return {"name": name, "via": "CNAME", "cname": cname}, all_chain
        return None, all_chain
    except Exception:
        return None, all_chain


def _detect_cdn_by_asn(ip):
    """通过 IP 归属 ASN 识别 CDN（复用 ip-api.com）"""
    try:
        url = IP_API_URL.format(ip=ip)
        req = Request(url, headers={"User-Agent": "Mozilla/5.0 (ops-toolbox)"})
        with urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
        if data.get("status") != "success":
            return None, None
        asn = (data.get("as") or "").upper()
        org = (data.get("org") or "") + (data.get("isp") or "")
        matched = None
        for name, asns in CDN_ASN_RULES:
            for a in asns:
                if a in asn or a in org.upper():
                    matched = name
                    break
            if matched:
                break
        return matched, data
    except Exception:
        return None, None


def cdn_lookup(host):
    """CDN 识别：CNAME 特征 + IP ASN 归属"""
    # 解析 IP（取第一个非内网地址）
    ip = None
    try:
        infos = socket.getaddrinfo(host, None, socket.AF_INET)
        for info in infos:
            candidate = info[4][0]
            if not _is_internal_ip(candidate):
                ip = candidate
                break
    except Exception:
        pass
    if not ip:
        return {"code": 1, "message": "无法解析目标域名"}
    # 1) CNAME 特征识别（同时返回完整 CNAME 链）
    cname_hit, cname_chain = _detect_cdn_by_cname(host)
    # 2) ASN 识别
    asn_hit, ipinfo = _detect_cdn_by_asn(ip)
    provider = cname_hit["name"] if cname_hit else (asn_hit or None)
    # 未识别时给出更明确的提示
    not_recognized = not provider
    if not_recognized:
        hint = "未识别到常见 CDN（可能是边缘加速/自建 CDN/直连源站）"
    else:
        hint = provider
    return {"code": 0, "data": {
        "host": host,
        "resolved_ip": ip,
        "cdn": hint,
        "provider": provider,
        "detected_by": cname_hit["via"] if cname_hit else ("ASN 归属" if asn_hit else "无"),
        "cname_chain": cname_chain,
        "matched_cname": cname_hit["cname"] if cname_hit else None,
        "ip_org": (ipinfo or {}).get("org", ""),
        "ip_as": (ipinfo or {}).get("as", ""),
        "ip_country": (ipinfo or {}).get("country", ""),
        "ip_region": (ipinfo or {}).get("regionName", ""),
        "ip_city": (ipinfo or {}).get("city", ""),
    }}


# ==================== 8. Whois 查询（RDAP 公共 API，跨平台统一） ====================

RDAP_BOOTSTRAP_URL = "https://rdap.org/domain/{domain}"


def whois_query(domain):
    """域名 Whois 查询（跨平台统一走 RDAP 公共 API，无 key、结构化 JSON）。
    注：macOS 本地 whois 命令常只返回 IANA referral（无实际数据），故不再依赖本地命令。
    """
    domain = domain.strip().lower().rstrip('.')
    try:
        url = RDAP_BOOTSTRAP_URL.format(domain=domain)
        req = Request(url, headers={"User-Agent": "Mozilla/5.0 (ops-toolbox)", "Accept": "application/rdap+json"})
        with urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode())
        return {"code": 0, "data": {"domain": domain, "source": "RDAP 公共 API", "rdap": data}}
    except Exception as e:
        return {"code": 1, "message": f"Whois 查询失败: {str(e)}"}


# ==================== 9. SSL 检测（证书信息 + TLS 协议支持） ====================

TLS_VERSIONS = [
    ("TLSv1.0", ssl.TLSVersion.TLSv1),
    ("TLSv1.1", ssl.TLSVersion.TLSv1_1),
    ("TLSv1.2", ssl.TLSVersion.TLSv1_2),
    ("TLSv1.3", ssl.TLSVersion.TLSv1_3),
]


def _probe_tls(host, port, version):
    """探测某个 TLS 协议版本是否被目标支持"""
    try:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ctx.minimum_version = version
        ctx.maximum_version = version
        with socket.create_connection((host, port), timeout=4) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as tsock:
                cipher = tsock.cipher()
                return True, cipher[0] if cipher else ""
    except (ssl.SSLError, OSError, socket.timeout):
        return False, ""
    except Exception:
        return False, ""


def ssl_inspect(host, port=443):
    """SSL 证书信息 + TLS 协议支持矩阵"""
    if not (1 <= int(port) <= 65535):
        return {"code": 1, "message": "端口范围 1-65535"}
    port = int(port)
    # 1) 证书信息（用 cryptography 库解析 DER 证书，跨平台可靠）
    cert_info = None
    try:
        from cryptography import x509
        from cryptography.hazmat.backends import default_backend
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with socket.create_connection((host, port), timeout=6) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as tsock:
                der_cert = tsock.getpeercert(binary_form=True)
                cert = x509.load_der_x509_certificate(der_cert, default_backend())
                import hashlib
                fingerprint = hashlib.sha256(der_cert).hexdigest()
                # 主题与颁发者
                subj = cert.subject
                iss = cert.issuer
                def get_cn(name):
                    try:
                        return name.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)[0].value
                    except Exception:
                        return ""
                def get_org(name):
                    try:
                        return name.get_attributes_for_oid(x509.oid.NameOID.ORGANIZATION_NAME)[0].value
                    except Exception:
                        return ""
                san = []
                try:
                    ext = cert.extensions.get_extension_for_oid(x509.oid.ExtensionOID.SUBJECT_ALTERNATIVE_NAME)
                    san = [entry.value for entry in ext.value]
                except Exception:
                    pass
                cert_info = {
                    "subject_cn": get_cn(subj),
                    "subject_o": get_org(subj),
                    "issuer_cn": get_cn(iss),
                    "issuer_o": get_org(iss),
                    "not_before": str(cert.not_valid_before_utc),
                    "not_after": str(cert.not_valid_after_utc),
                    "san": san,
                    "serial": format(cert.serial_number, 'X'),
                    "version": cert.version.name if hasattr(cert.version, 'name') else str(cert.version),
                    "signature_algorithm": cert.signature_algorithm_oid._name if hasattr(cert.signature_algorithm_oid, '_name') else str(cert.signature_algorithm_oid),
                    "fingerprint_sha256": fingerprint,
                    "tls_version_used": tsock.version(),
                    "cipher_used": (tsock.cipher() or [None])[0],
                }
    except Exception as e:
        return {"code": 1, "message": f"SSL 连接失败: {str(e)}（可能未启用 HTTPS 或端口不通）"}

    # 2) TLS 协议支持矩阵（逐个探测）
    tls_matrix = []
    for name, ver in TLS_VERSIONS:
        supported, cipher = _probe_tls(host, port, ver)
        tls_matrix.append({"version": name, "supported": supported, "cipher": cipher})

    return {"code": 0, "data": {"host": host, "port": port, "cert": cert_info, "tls_matrix": tls_matrix}}

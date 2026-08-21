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


# 中英映射（ip-api.com 的 lang=zh-CN 部分翻译不完整，补充常用）
LOCALIZE_COUNTRY = {
    "Singapore": "新加坡", "United States": "美国", "United Kingdom": "英国",
    "China": "中国", "Hong Kong": "中国香港", "Taiwan": "中国台湾", "Macao": "中国澳门",
    "Japan": "日本", "South Korea": "韩国", "Korea, Republic of": "韩国",
    "North Korea": "朝鲜", "Mongolia": "蒙古", "India": "印度", "Pakistan": "巴基斯坦",
    "Thailand": "泰国", "Vietnam": "越南", "Malaysia": "马来西亚", "Singapore": "新加坡",
    "Indonesia": "印度尼西亚", "Philippines": "菲律宾", "Cambodia": "柬埔寨",
    "Myanmar": "缅甸", "Laos": "老挝", "Nepal": "尼泊尔", "Bangladesh": "孟加拉",
    "Russia": "俄罗斯", "Ukraine": "乌克兰", "Germany": "德国", "France": "法国",
    "Italy": "意大利", "Spain": "西班牙", "Portugal": "葡萄牙", "Netherlands": "荷兰",
    "Belgium": "比利时", "Switzerland": "瑞士", "Austria": "奥地利", "Sweden": "瑞典",
    "Norway": "挪威", "Finland": "芬兰", "Denmark": "丹麦", "Poland": "波兰",
    "Czech Republic": "捷克", "Czechia": "捷克", "Hungary": "匈牙利", "Greece": "希腊",
    "Ireland": "爱尔兰", "Iceland": "冰岛", "Turkey": "土耳其", "Israel": "以色列",
    "Saudi Arabia": "沙特阿拉伯", "United Arab Emirates": "阿联酋", "Iran": "伊朗",
    "Iraq": "伊拉克", "Egypt": "埃及", "Turkey": "土耳其", "Israel": "以色列",
    "South Africa": "南非", "Kenya": "肯尼亚", "Nigeria": "尼日利亚",
    "Australia": "澳大利亚", "New Zealand": "新西兰",
    "Canada": "加拿大", "Mexico": "墨西哥", "Brazil": "巴西", "Argentina": "阿根廷",
    "Chile": "智利", "Colombia": "哥伦比亚",
}
LOCALIZE_REGION = {
    # 新加坡行政区
    "North West": "西北区", "South West": "西南区", "North East": "东北区",
    "South East": "东南区", "Central": "中部",
    # 中国（用拼音时大陆省份不需要翻译，但备用）
    "Beijing": "北京", "Shanghai": "上海", "Tianjin": "天津", "Chongqing": "重庆",
    # 通用方位
    "North": "北部", "South": "南部", "East": "东部", "West": "西部",
    "Northeast": "东北", "Northwest": "西北", "Southeast": "东南", "Southwest": "西南",
    # 美国州
    "California": "加利福尼亚", "New York": "纽约", "Texas": "得克萨斯",
    "Washington": "华盛顿", "Illinois": "伊利诺伊", "Massachusetts": "马萨诸塞",
    "Virginia": "弗吉尼亚", "Georgia": "乔治亚", "Florida": "佛罗里达",
    "Oregon": "俄勒冈", "Colorado": "科罗拉多", "Arizona": "亚利桑那",
    "Nevada": "内华达", "Ohio": "俄亥俄", "Pennsylvania": "宾夕法尼亚",
    # 英文省份 → 中文（节选）
    "Guangdong": "广东", "Sichuan": "四川", "Zhejiang": "浙江", "Jiangsu": "江苏",
    "Shandong": "山东", "Henan": "河南", "Hubei": "湖北", "Hunan": "湖南",
    "Fujian": "福建", "Anhui": "安徽", "Shanxi": "山西", "Heilongjiang": "黑龙江",
    "Liaoning": "辽宁", "Jilin": "吉林", "Shaanxi": "陕西", "Gansu": "甘肃",
    "Yunnan": "云南", "Guangxi": "广西", "Hainan": "海南", "Fujian": "福建",
    # 日本
    "Tokyo": "东京都", "Osaka": "大阪府", "Kyoto": "京都府",
    # 澳大利亚
    "New South Wales": "新南威尔士", "Victoria": "维多利亚州",
    "Queensland": "昆士兰", "Western Australia": "西澳大利亚",
    # 香港十八区
    "Central and Western": "中西区", "Eastern": "东区", "Wan Chai": "湾仔区",
    "Yau Tsim Mong": "油尖旺区", "Kowloon City": "九龙城区", "Kwun Tong": "观塘区",
    "Tsuen Wan": "荃湾区", "Tuen Mun": "屯门区", "Yuen Long": "元朗区",
    "Northern": "北区", "Sha Tin": "沙田区", "Tai Po": "大埔区",
    "Sai Kung": "西贡区", "Islands": "离岛区",
}
LOCALIZE_CITY = {
    "Singapore": "新加坡", "Hong Kong": "香港", "Tokyo": "东京", "Osaka": "大阪",
    "Seoul": "首尔", "Bangkok": "曼谷", "Kuala Lumpur": "吉隆坡", "Jakarta": "雅加达",
    "Manila": "马尼拉", "Ho Chi Minh City": "胡志明市", "Hanoi": "河内",
    "Sydney": "悉尼", "Melbourne": "墨尔本", "Brisbane": "布里斯班",
    "Auckland": "奥克兰", "Wellington": "惠灵顿",
    "New York": "纽约", "Los Angeles": "洛杉矶", "San Francisco": "旧金山",
    "Chicago": "芝加哥", "Washington": "华盛顿", "Boston": "波士顿",
    "Houston": "休斯顿", "Dallas": "达拉斯", "Seattle": "西雅图", "Atlanta": "亚特兰大",
    "London": "伦敦", "Paris": "巴黎", "Berlin": "柏林", "Munich": "慕尼黑",
    "Frankfurt": "法兰克福", "Amsterdam": "阿姆斯特丹", "Madrid": "马德里",
    "Barcelona": "巴塞罗那", "Rome": "罗马", "Milan": "米兰", "Moscow": "莫斯科",
    "Istanbul": "伊斯坦布尔", "Dubai": "迪拜", "Mumbai": "孟买", "New Delhi": "新德里",
    "Toronto": "多伦多", "Vancouver": "温哥华", "Montreal": "蒙特利尔",
    "Mexico City": "墨西哥城", "São Paulo": "圣保罗", "Buenos Aires": "布宜诺斯艾利斯",
    "Guangzhou": "广州", "Shenzhen": "深圳", "Beijing": "北京", "Shanghai": "上海",
    "Hangzhou": "杭州", "Nanjing": "南京", "Chengdu": "成都", "Wuhan": "武汉",
    "Xi'an": "西安", "Tianjin": "天津", "Chongqing": "重庆", "Suzhou": "苏州",
    "Taipei": "台北",
}


def _localize(value, mapping):
    """中英映射：命中返回中文，否则保留原值（小写比较避免大小写问题）"""
    if not value:
        return value
    if value in mapping:
        return mapping[value]
    # 尝试 Title Case 匹配
    return mapping.get(value.title(), value)


def _localize_geo(data):
    """对 IP 归属数据中的 country/region/city 做中英转换"""
    if not isinstance(data, dict):
        return data
    data["country"] = _localize(data.get("country", ""), LOCALIZE_COUNTRY)
    data["region"] = _localize(data.get("region", ""), LOCALIZE_REGION)
    data["city"] = _localize(data.get("city", ""), LOCALIZE_CITY)
    return data


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
        result = {
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
        }
        _localize_geo(result)
        return {"code": 0, "data": result}
    except Exception as e:
        return {"code": 1, "message": f"IP 归属查询失败: {str(e)}"}


def _fetch_myip_from_cip(timeout=1.5):
    """通过 cip.cc 获取服务端自身公网 IP（这是浏览器访问服务器时的网络出口 IP）。
    cip.cc 返回纯文本格式：
        IP      : 210.184.73.156
        地址    : 新加坡
        ...
    """
    import re as _re
    try:
        req = Request("http://cip.cc", headers={"User-Agent": "Mozilla/5.0 (ops-toolbox)"})
        with urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="replace")
        m = _re.search(r'IP\s*:\s*(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})', text)
        return m.group(1) if m else None
    except Exception:
        return None


def _fetch_myip_from_api(ipify_timeout=1.5):
    """备用：通过 api.ipify.org 获取出口 IP（返回纯文本）"""
    try:
        req = Request("https://api.ipify.org", headers={"User-Agent": "Mozilla/5.0 (ops-toolbox)"})
        with urlopen(req, timeout=ipify_timeout) as resp:
            return resp.read().decode("utf-8").strip() or None
    except Exception:
        return None


def _get_egress_ip(request_ip=None):
    """获取服务端公网出口 IP（并行查询 cip.cc + ipify.org，1.0 秒首返回即停）"""
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        f1 = ex.submit(_fetch_myip_from_cip)
        f2 = ex.submit(_fetch_myip_from_api)
        # 仅 1.0 秒首返回即停（不卡 HTML 加载）
        done, _ = concurrent.futures.wait(
            [f1, f2],
            timeout=1.0,
            return_when=concurrent.futures.FIRST_COMPLETED
        )
        for fut in done:
            try:
                ip = fut.result()
                if ip:
                    return ip, 'cip.cc/ipify.org'
            except Exception:
                continue
    # 兜底：返回 remote_addr（让前端 JS 后续 XHR 重新查询）
    return (request_ip or '').strip() or None, 'X-Forwarded-For/remote_addr'


def myip_lookup(ip):
    """本机出口 IP 查询（并行：cip.cc/ipify 拿 IP，ip-api 查归属，总限时 2s）
    1. 并行查询 cip.cc / ipify.org 拿公网 IP
    2. 内网 IP 直接标记返回
    3. 公网 IP 走 ip_lookup（限 1.5s 超时）
    """
    import concurrent.futures
    # 并行：cip/ipify + 归属查询（公网 IP 才查归属）
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        f1 = ex.submit(_get_egress_ip, ip)
        # 等 cip/ipify 完成 0.5s（如果超时就用传入 ip 走内网 fallback）
        done, _ = concurrent.futures.wait([f1], timeout=0.5, return_when=concurrent.futures.FIRST_COMPLETED)
        public_ip, _src = None, None
        for fut in done:
            try:
                public_ip, _src = fut.result()
            except Exception:
                pass
        # 若 0.5s 内没拿到 IP，fallback 试传入 ip 是否公网（X-Forwarded-For/remote_addr）
        if not public_ip:
            public_ip = (ip or '').strip() or None
        if not public_ip:
            return {"code": 1, "message": "无法获取出口 IP"}

        # 内网 IP：直接标记（无需调用 ip-api）
        try:
            addr = ipaddress.ip_address(public_ip)
            if addr.is_loopback or addr.is_private or addr.is_link_local or addr.is_unspecified:
                return {"code": 0, "data": {
                    "ip": public_ip, "country": "内网/本地", "region": "-", "city": "-",
                    "isp": "本地回环/内网地址", "org": "内网", "as": "-", "asname": "-",
                    "lat": None, "lon": None, "timezone": "-",
                    "reverse": "-", "mobile": False, "proxy": False, "hosting": False,
                    "_internal": True,
                }}
        except ValueError:
            return {"code": 1, "message": "客户端 IP 格式异常"}

        # 公网 IP：用 ThreadPoolExecutor 总限时 1.5s 查归属
        f2 = ex.submit(ip_lookup, public_ip)
        done2, _ = concurrent.futures.wait([f2], timeout=1.5)
        if not done2:
            # 超时：返回最简版（只显示 IP，不卡）
            return {"code": 0, "data": {
                "ip": public_ip, "country": "-", "region": "-", "city": "-",
                "isp": "-", "org": "-", "as": "-", "asname": "-",
                "lat": None, "lon": None, "timezone": "-",
                "reverse": "-", "mobile": False, "proxy": False, "hosting": False,
                "_quick": True,
            }}
        try:
            return f2.result()
        except Exception as e:
            return {"code": 0, "data": {
                "ip": public_ip, "country": "-", "region": "-", "city": "-",
                "isp": "-", "org": "-", "as": "-", "asname": "-",
                "_error": str(e)[:80],
            }}


# ==================== 2. PING 检测 ====================

def ping_detect(host, count=4, timeout=5):
    """ICMP 连通性检测（跨平台命令，兼容 macOS/Linux/Windows 输出格式）

    K8s 容器场景：单包超时 -W 默认 2s，subprocess 超时 = 单包×包数+5s，
    典型 4 包 ≈ 13s 完成（避免触发 nginx ingress 30s 超时 → 504）。
    """
    if SYSTEM == "Windows":
        cmd = ["ping", "-n", str(count), "-w", str(timeout * 1000), host]
    else:
        cmd = ["ping", "-c", str(count), "-W", str(timeout), host]
    t0 = time.time()
    ok, stdout, stderr = _run_cmd(cmd, timeout=(timeout * count) + 5)
    cost = round(time.time() - t0, 2)
    if not ok and "命令不存在" in stderr:
        return {"code": 1, "message": stderr}
    text = stdout or stderr or ""
    result = {
        "host": host, "output": text, "cost": cost, "samples": [],
        # 初始化可选字段（ping 完全失败时也保证字段存在，前端不报 undefined）
        "min": None, "avg": None, "max": None, "loss": None, "ttl": None, "success": False,
    }

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
    # 退路：如果没统计行但有逐行延迟样本，按样本统计
    if result.get("avg") is None and result["samples"]:
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
        # mtr --json 实际输出 {"report":{"mtr":{...},"hubs":[...]},"report":{...}} 顶层带 report 嵌套键
        return {"code": 0, "data": {"host": host, "mode": "mtr", "report": data.get("report", data)}}
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

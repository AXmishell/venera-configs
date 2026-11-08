#!/usr/bin/env python3
"""栗子漫画 (com.hbsclj.uth) 协议辅助工具。

支持：
  * 解密 DNS TXT 中的 API 域名配置（AES-256-ECB）
  * 解密 COS 上的启动配置（同一把 AES 密钥）
  * 生成带 lzsign 签名的 API URL，或直接请求公开接口
  * 解密 $jp$ 图片（xorshift32 流密码，seed = FNV1a32）
  * 探测章节封面所在目录的公开图片页码

用法示例：
    python3 decrypt_lizimh.py txt 'ocjketotf...='
    python3 decrypt_lizimh.py discover
    python3 decrypt_lizimh.py bootstrap
    python3 decrypt_lizimh.py sign /app/api/home/data
    python3 decrypt_lizimh.py fetch /app/api/v2/detail/22613
    python3 decrypt_lizimh.py image --url 'https://t1.imge.store/Manual/.../65.webp' -o 65.webp
    python3 decrypt_lizimh.py pages --cover '$jp$/102/58342/.../17.webp'

依赖：Python 3.8+，openssl 命令行（AES-256-ECB）。
HTTP 请求遵循 HTTP_PROXY / HTTPS_PROXY 环境变量。
"""

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_API = "https://mh.lizimh.net"
SIGN_PREFIX = "q2sIObYCp2uBZgCNBlY93J3z67hK0wS"
TXT_KEY = b"f8d992c74b29491d8a3e3fd5f07389d8"
PACKNAME = "com.jy.zyds"
APP_SIGN256 = ""
BOOTSTRAP_URL = (
    "https://lz-1382057604.cos.ap-hongkong.myqcloud.com/"
    "5A6F4D2B7E9A1C3D8F0B2E4A6C8E0D2F4B6A8C0E2D4F6A8B0C2E4D6F8A0C2E4B.json"
)
TXT_NAMES = ["adnet.lizimh.com", "adnet.lizi.lat"]
DOH_PROVIDERS = [
    "https://dns.alidns.com/resolve",
    "https://dns.google/resolve",
]
IMAGE_HOST = "https://media.imgo.buzz"
JP_HOST = "https://t1.imge.store"
IMAGE_SALT = "imgio-fast-obfuscation-v7"
IMAGE_VERSION = "v7"
USER_AGENT = "Dart/3.5 (dart:io)"


def die(message):
    print("错误: " + message, file=sys.stderr)
    raise SystemExit(1)


def aes_ecb_decrypt(data, key):
    """调用 openssl 做无填充 AES-ECB 解密，返回原始字节。"""
    if len(key) not in (16, 24, 32):
        die("AES 密钥长度必须是 16/24/32 字节")
    cmd = [
        "openssl",
        "enc",
        "-aes-256-ecb" if len(key) == 32 else
        ("-aes-192-ecb" if len(key) == 24 else "-aes-128-ecb"),
        "-d",
        "-nopad",
        "-K",
        key.hex(),
    ]
    proc = subprocess.run(cmd, input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        die("openssl 解密失败: " + proc.stderr.decode("utf-8", "replace").strip())
    return proc.stdout


def strip_padding(data):
    """去掉 PKCS7 或栗子服务端使用的重复尾字节填充。"""
    if not data:
        return data
    padding = data[-1]
    if 0 < padding <= 16 and padding <= len(data):
        return data[:-padding]
    return data


def decode_txt(value):
    """TXT 记录 -> 明文字符串（通常是 https://mh.lizimh.net）。"""
    encoded = str(value or "").strip().strip('"')
    if not encoded:
        die("TXT 内容为空")
    try:
        cipher = base64.b64decode(encoded, validate=True)
    except Exception:
        die("TXT 不是有效的 Base64")
    plain = strip_padding(aes_ecb_decrypt(cipher, TXT_KEY))
    text = plain.decode("utf-8", "replace").replace("\x00", "").strip().rstrip("/")
    if not re.match(r"^https?://[^/?#]+$", text, re.I):
        die("解密结果不是合法域名: " + repr(text))
    return text


def http_request(url, method="GET", headers=None, timeout=30, fatal=True):
    request = urllib.request.Request(url, method=method)
    default_headers = {
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }
    for key, value in (headers or {}).items():
        default_headers[key] = value
    for key, value in default_headers.items():
        request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read(), dict(response.headers)
    except urllib.error.HTTPError as error:
        return error.code, error.read(), dict(error.headers)
    except Exception as error:
        if fatal:
            die("请求失败: %s (%s)" % (url, error))
        raise


def http_json(url, method="GET", headers=None, fatal=True):
    try:
        status, body, _ = http_request(url, method, headers, fatal=fatal)
    except Exception:
        return 0, None
    try:
        return status, json.loads(body.decode("utf-8", "replace"))
    except Exception:
        return status, None


def split_query(path):
    """拆分 path 与已有 query，query 保留原始 key=value 片段。"""
    if "?" not in path:
        return path, []
    path_part, query_part = path.split("?", 1)
    parts = [item for item in query_part.split("&") if item]
    return path_part, parts


def encode_pair(key, value):
    return urllib.parse.quote(str(key), safe="") + "=" + urllib.parse.quote(str(value), safe="")


def signed_url(path, query=None, base=DEFAULT_API, timestamp=None):
    """按照官方算法生成带 lzsign / t 的完整 URL。"""
    path_only, existing = split_query(path)
    parts = []
    if existing:
        parts.extend(existing)
    elif query:
        for item in query:
            if isinstance(item, str):
                parts.append(item)
            else:
                parts.append(encode_pair(item[0], item[1]))
    parts = [
        item for item in parts
        if item.split("=", 1)[0] not in ("lzsign", "t")
    ]

    def has_key(name):
        return any(item.split("=", 1)[0] == name for item in parts)

    if path_only in ("/app/api/home/data", "/app/api/configv2"):
        if not has_key("packname"):
            parts.append("packname=" + PACKNAME)
        if not has_key("appsign256"):
            parts.append("appsign256=" + APP_SIGN256)
    if path_only == "/app/api/configv2" and not has_key("platform"):
        parts.append("platform=ios")

    stamp = str(timestamp if timestamp is not None else int(time.time()))
    if not re.match(r"^\d{10}$", stamp):
        die("时间戳必须是 10 位秒级 Unix 时间")
    signature = hashlib.md5((SIGN_PREFIX + path_only + stamp).encode("utf-8")).hexdigest()
    parts.append("lzsign=" + signature)
    parts.append("t=" + stamp)
    return base.rstrip("/") + path_only + "?" + "&".join(parts)


def cmd_txt(args):
    print(decode_txt(args.value))


def cmd_discover(args):
    found = []
    for name in TXT_NAMES:
        resolved = False
        for provider in DOH_PROVIDERS:
            url = provider + "?" + urllib.parse.urlencode({"name": name, "type": "TXT"})
            status, data = http_json(url, fatal=False)
            if status != 200 or not data or data.get("Status") != 0:
                continue
            for answer in data.get("Answer") or []:
                try:
                    domain = decode_txt(answer.get("data", ""))
                except SystemExit:
                    continue
                if domain not in found:
                    found.append(domain)
                    print("%s\t%s" % (name, domain))
                resolved = True
                break
            if resolved:
                break
    if not found:
        die("没有解析到可用域名")


def cmd_bootstrap(args):
    url = args.url or BOOTSTRAP_URL
    status, body, _ = http_request(url)
    if status != 200:
        die("下载启动配置失败 HTTP %s" % status)
    encoded = body.decode("utf-8", "replace").strip()
    try:
        cipher = base64.b64decode(encoded, validate=True)
    except Exception:
        die("启动配置不是有效的 Base64")
    plain = strip_padding(aes_ecb_decrypt(cipher, TXT_KEY))
    text = plain.decode("utf-8", "replace").replace("\x00", "").strip()
    try:
        parsed = json.loads(text)
    except Exception:
        print(text)
        return
    print(json.dumps(parsed, ensure_ascii=False, indent=2))


def cmd_sign(args):
    path = args.path
    query = []
    for key, value in args.param or []:
        query.append((key, value))
    if args.query:
        query.extend([item for item in args.query.split("&") if item])
    print(signed_url(path, query, base=args.base, timestamp=args.timestamp))


def cmd_fetch(args):
    query = []
    for key, value in args.param or []:
        query.append((key, value))
    url = signed_url(args.path, query, base=args.base, timestamp=args.timestamp)
    headers = {}
    for item in args.header or []:
        if ":" in item:
            key, value = item.split(":", 1)
            headers[key.strip()] = value.strip()
    status, body, _ = http_request(url, headers=headers)
    if args.output:
        with open(args.output, "wb") as file:
            file.write(body)
        print("HTTP %s -> %s (%d bytes)" % (status, args.output, len(body)))
        return
    text = body.decode("utf-8", "replace")
    if args.json:
        try:
            text = json.dumps(json.loads(text), ensure_ascii=False, indent=2)
        except Exception:
            pass
    print("HTTP %s" % status)
    print(text)


def is_image(data):
    if len(data) < 12:
        return False
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return True
    if data[:3] == b"\xff\xd8\xff":
        return True
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return True
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return True
    if data[4:8] == b"ftyp" and data[8:12] in (b"avif", b"avis"):
        return True
    return False


def image_seed(url):
    """FNV1a32(version + LF + salt + LF + URI path/query)。"""
    value = str(url or "").split("#", 1)[0]
    match = re.match(r"^[a-z][a-z0-9+.-]*://[^/?#]*(.*)$", value, re.I)
    path = match.group(1) if match else value
    if match and (not path or path.startswith("?")):
        path = "/" + path
    raw = (IMAGE_VERSION + "\n" + IMAGE_SALT + "\n" + path).encode("utf-8")
    result = 0x811C9DC5
    for byte in raw:
        result ^= byte
        result = (result * 0x01000193) & 0xFFFFFFFF
    return result or 0x9E3779B9


def xorshift_step(state):
    state &= 0xFFFFFFFF
    state ^= (state << 13) & 0xFFFFFFFF
    state &= 0xFFFFFFFF
    state ^= state >> 17
    state &= 0xFFFFFFFF
    state ^= (state << 5) & 0xFFFFFFFF
    return state & 0xFFFFFFFF


def decode_image(data, url):
    """$jp$ 图片解码；已经是明文图片时原样返回。"""
    if is_image(data):
        return data, "plain"
    output = bytearray(data)
    state = image_seed(url)
    limit = min(len(output), 65536)
    for index in range(limit):
        state = xorshift_step(state)
        output[index] ^= state & 0xFF
    if not is_image(output):
        die("图片解密失败：头部仍不是已知图片格式")
    return bytes(output), "xor(seed=0x%08x)" % image_seed(url)


def normalize_jp_url(value):
    """把 $jp$ 路径或普通路径补全为可下载 URL。"""
    value = str(value or "").strip()
    if re.match(r"^https?://", value, re.I):
        return value
    if value.startswith("$jp$"):
        path = re.sub(r"^\$jp\$(?:cf)?", "", value)
        if not path.startswith("/"):
            path = "/" + path
        return JP_HOST + path
    if not value.startswith("/"):
        value = "/" + value
    return IMAGE_HOST + value


def cmd_image(args):
    if args.input:
        with open(args.input, "rb") as file:
            data = file.read()
        url = args.url or args.input
    elif args.url:
        url = normalize_jp_url(args.url)
        status, data, _ = http_request(url)
        if status != 200:
            die("下载图片失败 HTTP %s" % status)
    else:
        die("需要 --input 或 --url")

    seed_url = normalize_jp_url(url)
    decoded, mode = decode_image(data, seed_url)
    output = args.output
    if not output:
        extension = os.path.splitext(urllib.parse.urlparse(seed_url).path)[1] or ".bin"
        output = "decrypted" + extension
    with open(output, "wb") as file:
        file.write(decoded)
    print("输入 %d 字节，%s，输出 %s (%d 字节)" % (len(data), mode, output, len(decoded)))


def head_exists(url):
    try:
        status, body, headers = http_request(url, method="HEAD", timeout=15, fatal=False)
    except Exception:
        return None, 0
    if status in (200, 206):
        return True, int(headers.get("Content-Length") or 0)
    if status in (403, 404, 410):
        return False, 0
    return None, 0


def probe_pages(cover, max_pages=500):
    """从章节封面路径探测同目录下的连续页码。"""
    cover = str(cover or "").strip()
    match = re.match(r"^(.*?)/(\d+)\.([A-Za-z0-9]+)(?:\?.*)?$", cover)
    if not match:
        die("封面路径格式不正确: " + cover)
    directory, _, extension = match.groups()
    if directory.startswith("$jp$"):
        base_cover = "$jp$" + directory[4:]
    else:
        base_cover = directory

    def exists(page):
        url = normalize_jp_url(base_cover + "/" + str(page) + "." + extension)
        result, size = head_exists(url)
        return result, url, size

    first = None
    for page in range(1, 13):
        result, url, size = exists(page)
        if result is True:
            first = page
            break
    if first is None:
        for page in range(13, 49):
            result, url, size = exists(page)
            if result is True:
                first = page
                break
    if first is None:
        die("1~48 页均不存在")

    low = first
    step = 1
    high = first + 1
    while high <= max_pages:
        result, url, size = exists(high)
        if result is True:
            low = high
            step *= 2
            high = low + step
        elif result is False:
            break
        else:
            high += 1
    if high > max_pages:
        high = max_pages + 1
    while low + 1 < high:
        middle = (low + high) // 2
        result, url, size = exists(middle)
        if result is True:
            low = middle
        else:
            high = middle
    for offset in range(1, 5):
        result, url, size = exists(low + offset)
        if result is True:
            low += offset
        else:
            break

    print("目录: %s" % base_cover)
    print("扩展名: %s" % extension)
    print("页码: %d..%d（共 %d 页）" % (first, low, low - first + 1))
    for page in range(first, low + 1):
        print(normalize_jp_url(base_cover + "/" + str(page) + "." + extension))


def build_parser():
    parser = argparse.ArgumentParser(
        description="栗子漫画 (com.hbsclj.uth) 协议辅助工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    txt = subparsers.add_parser("txt", help="解密 DNS TXT 域名配置")
    txt.add_argument("value", help="TXT 记录内容（Base64）")
    txt.set_defaults(func=cmd_txt)

    discover = subparsers.add_parser("discover", help="通过 DoH 查询并解密当前 API 域名")
    discover.set_defaults(func=cmd_discover)

    bootstrap = subparsers.add_parser("bootstrap", help="下载并解密 COS 启动配置")
    bootstrap.add_argument("--url", help="自定义配置 URL")
    bootstrap.set_defaults(func=cmd_bootstrap)

    sign = subparsers.add_parser("sign", help="生成带 lzsign 签名的 URL")
    sign.add_argument("path", help="例如 /app/api/home/data，可同时带 query")
    sign.add_argument("--base", default=DEFAULT_API, help="API 根地址")
    sign.add_argument("--param", nargs=2, action="append", metavar=("KEY", "VALUE"),
                      help="追加 query 参数，值会自动 URL 编码")
    sign.add_argument("--query", help="直接追加原始 query，例如 a=1&b=2")
    sign.add_argument("--timestamp", type=int, help="固定 10 位时间戳（调试用）")
    sign.set_defaults(func=cmd_sign)

    fetch = subparsers.add_parser("fetch", help="请求签名后的公开 API")
    fetch.add_argument("path", help="接口路径")
    fetch.add_argument("--base", default=DEFAULT_API, help="API 根地址")
    fetch.add_argument("--param", nargs=2, action="append", metavar=("KEY", "VALUE"))
    fetch.add_argument("--header", action="append", metavar="KEY:VALUE")
    fetch.add_argument("--timestamp", type=int, help="固定时间戳（调试用）")
    fetch.add_argument("--json", action="store_true", help="格式化 JSON 输出")
    fetch.add_argument("-o", "--output", help="保存响应到文件")
    fetch.set_defaults(func=cmd_fetch)

    image = subparsers.add_parser("image", help="解密 $jp$ 图片")
    image.add_argument("--input", help="本地加密图片文件")
    image.add_argument("--url", help="图片 URL 或 $jp$ 路径（同时作为 seed 来源）")
    image.add_argument("-o", "--output", help="输出文件")
    image.set_defaults(func=cmd_image)

    pages = subparsers.add_parser("pages", help="从章节封面探测公开图片页码")
    pages.add_argument("--cover", required=True, help="章节接口返回的 cover 路径")
    pages.add_argument("--max", type=int, default=500, help="最大探测页码")
    pages.set_defaults(func=lambda args: probe_pages(args.cover, args.max))

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

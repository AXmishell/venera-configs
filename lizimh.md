# 栗子漫画 (lizimh) 协议分析

本文记录 `com.hbsclj.uth`（栗子漫画官方 Android 客户端）的网络协议、域名发现、图片混淆与章节读取方式，以及配套工具 `decrypt_lizimh.py` 的用法。

- 分析版本：`1.1.7`（versionCode 19）
- 应用形态：Flutter AOT，Java 层主要是 Flutter embedding，业务逻辑位于 `lib/arm64-v8a/libapp.so`
- 分析方式：从 `libapp.so` 提取字符串，结合公开接口响应验证；未修改或重新打包 APK
- 配套漫画源：仓库主分支的 `lizimh.js`

> 仅用于协议兼容、迁移与故障排查。常量、签名和域名都可能随客户端更新而变化。

---

## 1. 接口与签名

### 默认入口

```
https://mh.lizimh.net
```

### 请求签名

所有 `/app/api/*` 接口都带两个 query 参数：

```
lzsign = md5(SIGN_PREFIX + path + t)
t      = 秒级 Unix 时间戳（10 位）
```

其中：

```
SIGN_PREFIX = q2sIObYCp2uBZgCNBlY93J3z67hK0wS
```

`path` 不包含 query，例如 `/app/api/v2/detail/22613`；签名只使用 path 和 `t`。

首页和配置接口还需要补充：

```
packname=com.jy.zyds
appsign256=
```

`/app/api/configv2` 另外需要：

```
platform=ios
```

示例：

```bash
python3 decrypt_lizimh.py sign /app/api/home/data
# https://mh.lizimh.net/app/api/home/data?packname=com.jy.zyds&appsign256=&lzsign=...&t=...

python3 decrypt_lizimh.py fetch /app/api/v2/detail/22613 --json
```

### 已验证的公开接口

| 路径 | 说明 |
| --- | --- |
| `/app/api/home/data` | 首页分区、轮播、推荐 |
| `/app/api/configv2` | 分类、题材、图片线路、广告配置 |
| `/app/api/search/full?q=` | 搜索 |
| `/app/api/search/suggest?q=` | 搜索建议 |
| `/app/api/category/list?page=&tag=&class=&isend=` | 分类/筛选/分页 |
| `/app/api/rank/list` | 日漫/国漫/韩漫排行 |
| `/app/api/v2/detail/{comicId}` | 漫画详情、章节列表 |
| `/app/api/chapter/v3/{chapterId}` | 章节图片（需要登录 token） |
| `/app/api/user/login` | 邮箱密码登录，返回 token |
| `/app/api/user/register` | 注册 |
| `/app/api/collection/*` | 书架/收藏 |
| `/app/api/community/*` | 社区、评论 |

公开接口（首页、配置、搜索、分类、排行、详情）不需要登录。章节图片接口会校验 `authorization`，未登录返回：

```json
{"code":401,"data":null,"msg":"无权限"}
```

---

## 2. 域名发现

客户端通过 DNS TXT 获取当前 API 域名：

```
adnet.lizimh.com
adnet.lizi.lat
```

TXT 内容为 Base64，解码后用 AES-256-ECB 解密：

```
key = ASCII("f8d992c74b29491d8a3e3fd5f07389d8")   # 32 字节
```

当前记录：

| 域名 | 解密结果 |
| --- | --- |
| `adnet.lizimh.com` | `https://mh.lizimh.net/` |
| `adnet.lizi.lat` | `http://cdn.mechat.fun/`（旧图床入口） |

示例：

```bash
python3 decrypt_lizimh.py txt 'ocjketotfNqSPDUzH+PaEEnrfi7T9h6fDEZnUp4iPBA='
# https://mh.lizimh.net

python3 decrypt_lizimh.py discover
# adnet.lizimh.com	https://mh.lizimh.net
# adnet.lizi.lat	http://cdn.mechat.fun
```

`discover` 会通过阿里 DoH 和 Google DoH 查询 TXT，再逐个尝试解密。

### COS 启动配置

客户端还会读取腾讯 COS 上的一个启动配置：

```
https://lz-1382057604.cos.ap-hongkong.myqcloud.com/
5A6F4D2B7E9A1C3D8F0B2E4A6C8E0D2F4B6A8C0E2D4F6A8B0C2E4D6F8A0C2E4B.json
```

内容同样是 Base64 + AES-256-ECB（同一把 key），解密后是：

```json
{
  "domain": "http://ai.qsmm.fun/"
}
```

```bash
python3 decrypt_lizimh.py bootstrap
```

这是旧入口，当前优先使用 TXT 下发的 `mh.lizimh.net`。

---

## 3. 章节图片

### 3.1 官方接口（需要登录）

```
GET /app/api/chapter/v3/{chapterId}
authorization: {login token}
```

成功时返回 `data.pics`，元素是图片路径。部分路径以 `$jp$` 开头，需要按第 4 节处理。

登录：

```
POST /app/api/user/login
Content-Type: application/json

{"email":"...","pwd":"..."}
```

成功返回 `data.token`。token 直接放在 `authorization` 头里，不需要 `Bearer` 前缀。

### 3.2 未登录时的公开回退

详情接口的每个章节都带一张 `cover`，形如：

```
/3/22613/679798/8.webp
$jp$/102/58342/e40f5b367b8d028f/5beaeaa2/17.webp
```

`cover` 指向章节目录中的一张内页。统一按下面的规则还原：

```
目录 = cover 去掉最后的 /页码.扩展名
图片 = 目录/1.扩展名, 目录/2.扩展名, ... 直到 404
```

同目录页码通常从 1 连续递增。少数章节第一页不是 1，工具会先扫描 1~48 找起点。

```bash
python3 decrypt_lizimh.py pages --cover '/3/22613/679798/8.webp'
# 页码: 1..17（共 17 页）
# https://media.imgo.buzz/3/22613/679798/1.webp
# ...
```

注意：

- 普通路径走 `https://media.imgo.buzz`，返回明文图片。
- `$jp$` 路径走 `https://t1.imge.store`，返回混淆图片，需要第 4 节解密。
- 官方章节接口的图片顺序才是作者上传顺序；公开回退按文件名数字排序，极少数人工上传章节可能顺序不同。

---

## 4. 图片混淆

普通路径（如 `/3/...`、`/picY/...`）在 `media.imgo.buzz` 上是明文。

`$jp$` 路径（以及 `t1.imge.store` / `img2.mechat.fun`）返回的是 xorshift32 流密码混淆后的图片。

### 4.1 生成 seed

```
path = URL 的 path + query（不包含 scheme/host/fragment）
input = "v7\n" + "imgio-fast-obfuscation-v7" + "\n" + path
seed = FNV1a32(input)
```

FNV1a32：

```
hash = 0x811c9dc5
for byte in input:
    hash ^= byte
    hash = (hash * 0x01000193) & 0xffffffff
seed = hash or 0x9e3779b9
```

### 4.2 解密

只处理前 65536 字节：

```python
state = seed
for i in range(min(len(data), 65536)):
    state ^= (state << 13) & 0xffffffff
    state &= 0xffffffff
    state ^= state >> 17
    state &= 0xffffffff
    state ^= (state << 5) & 0xffffffff
    state &= 0xffffffff
    data[i] ^= state & 0xff
```

解密后头部应为 `RIFF....WEBP`、`FF D8 FF`（JPEG）、PNG 或 GIF。

### 4.3 工具

```bash
# 直接下载并解密
python3 decrypt_lizimh.py image \
  --url 'https://t1.imge.store/Manual/ueWvaPyf/NfyxAf4p/65.webp' \
  -o 65.webp

# 本地文件解密（URL 用于生成 seed）
python3 decrypt_lizimh.py image \
  --input encrypted.bin \
  --url 'https://t1.imge.store/Manual/ueWvaPyf/NfyxAf4p/65.webp' \
  -o 65.webp
```

输出会显示 seed 和检测到的图片格式。已经是明文的图片会原样输出，方便批量处理。

---

## 5. 图片线路

`/app/api/configv2` 的 `cfg_general.img_generator` 会下发一段 JavaScript 和线路列表。当前有效线路：

| 名称 | 地址 | 说明 |
| --- | --- | --- |
| 线路1 | `https://media.imgo.buzz` | 明文，速度快 |
| 线路2 | `http://img.mechat.fun` / `http://img2.mechat.fun` | 混淆 |
| 线路4 | 百度云 CDN 代理 | 代理 `media.imgo.buzz` |
| 线路5 | 腾讯云 CDN 代理 | 代理 `media.imgo.buzz` |

`lizimh.js` 默认：

- 普通路径 -> `media.imgo.buzz`
- `$jp$` 路径 -> `t1.imge.store` + 本地解密
- 可在源设置里切换 `media.imgo.buzz` / `t1.imge.store`

---

## 6. 工具命令汇总

```bash
# TXT 域名
python3 decrypt_lizimh.py txt '<base64>'
python3 decrypt_lizimh.py discover

# COS 启动配置
python3 decrypt_lizimh.py bootstrap

# 签名 / 请求
python3 decrypt_lizimh.py sign /app/api/home/data
python3 decrypt_lizimh.py sign /app/api/category/list --param tag 热血 --param page 1
python3 decrypt_lizimh.py fetch /app/api/v2/detail/22613 --json

# 图片解密
python3 decrypt_lizimh.py image --url '<t1/imge 或 $jp$ 路径>' -o out.webp

# 章节页码探测
python3 decrypt_lizimh.py pages --cover '/3/22613/679798/8.webp'
```

### 依赖

- Python 3.8+
- `openssl` 命令行（AES-256-ECB）
- HTTP 请求使用 Python 标准库，自动遵循 `HTTP_PROXY` / `HTTPS_PROXY`

### 常见问题

- `openssl` 不存在：安装 `openssl`，或改用带 AES 支持的 Python 环境。
- 域名解析失败：先确认本机 DNS/代理，再试 `discover`；TXT 可能被污染或更新。
- 图片解密失败：确认 `--url` 是实际请求的 URL（host + path），host 不参与 seed，但 path 必须一致。
- 章节探测失败：封面目录可能不是连续页码，或 CDN 对不存在页面返回非 404；可在漫画源里改用登录后的官方章节接口。

---

## 7. 已知限制

- 签名常量、TXT key、图片 salt 都来自 1.1.7；客户端升级后可能失效。
- 官方章节接口需要账号，且服务端可能按账号状态限制。
- 公开回退依赖图片目录可枚举；如果服务端改成签名 URL 或动态路径，需要重新分析。
- 本文不包含账号、token、Cookie 或任何个人凭据。

/**
 * ChapterImageDecoder - ported from keiyoushi/extensions-source (PR #16898)
 *
 * The /api/v2/chapter/getinfo endpoint returns the image list as an obfuscated
 * string instead of a plain array. This reverses the site's client-side decoder
 * back into the original JSON array of images.
 *
 * Pipeline: strip "J7r" prefix / "nQ" suffix -> split into 3 parts around the
 * "kD" and "W4s" markers -> reorder to part3+part1+part2 -> reverse every 2nd
 * 7-char block -> map the custom alphabet back to standard base64url -> base64
 * decode -> UTF-8 JSON.
 */
const STD = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
const CUSTOM = "_-9876543210abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ";
const DECODE_PREFIX = "J7r";
const DECODE_MARKER1 = "kD";
const DECODE_MARKER2 = "W4s";
const DECODE_SUFFIX = "nQ";
const DECODE_GROUP = 7;

// Precomputed lookup: custom-alphabet char code -> standard base64url char (-1 = invalid)
const DECODE_TABLE = new Array(128).fill(-1);
for (let i = 0; i < CUSTOM.length; i++) {
    DECODE_TABLE[CUSTOM.charCodeAt(i)] = STD.charCodeAt(i);
}

function decodeChapterImages(input) {
    if (typeof input !== "string" || !input.startsWith(DECODE_PREFIX) || !input.endsWith(DECODE_SUFFIX)) {
        throw "未知的章节数据格式";
    }
    const body = input.substring(DECODE_PREFIX.length, input.length - DECODE_SUFFIX.length);
    const payloadLen = body.length - DECODE_MARKER1.length - DECODE_MARKER2.length;
    if (payloadLen <= 0) {
        throw "未知的章节数据格式";
    }

    const aLen = Math.floor(payloadLen / 3);
    const bLen = Math.floor((payloadLen - aLen) / 2);
    const cLen = payloadLen - aLen - bLen;

    const part1 = body.substring(0, bLen);
    const marker1 = body.substring(bLen, bLen + DECODE_MARKER1.length);
    const part2 = body.substring(bLen + DECODE_MARKER1.length, bLen + DECODE_MARKER1.length + cLen);
    const marker2 = body.substring(bLen + DECODE_MARKER1.length + cLen, bLen + DECODE_MARKER1.length + cLen + DECODE_MARKER2.length);
    const part3 = body.substring(bLen + DECODE_MARKER1.length + cLen + DECODE_MARKER2.length);

    if (marker1 !== DECODE_MARKER1 || marker2 !== DECODE_MARKER2 || part3.length !== aLen) {
        throw "未知的章节数据格式";
    }

    // Reorder: part3 + part1 + part2
    const reordered = part3 + part1 + part2;

    // Unzigzag: reverse every 2nd GROUP-char block
    let unzigzagged = "";
    for (let i = 0, block = 0; i < reordered.length; i += DECODE_GROUP, block++) {
        const chunk = reordered.substring(i, Math.min(i + DECODE_GROUP, reordered.length));
        unzigzagged += (block % 2 === 1) ? chunk.split('').reverse().join('') : chunk;
    }

    // Map custom alphabet to standard base64url
    let standard = "";
    for (let i = 0; i < unzigzagged.length; i++) {
        const code = unzigzagged.charCodeAt(i);
        const mapped = code < DECODE_TABLE.length ? DECODE_TABLE[code] : -1;
        if (mapped < 0) {
            throw "无效的章节数据字符";
        }
        standard += String.fromCharCode(mapped);
    }

    // Base64 decode (pure JS, no atob). Convert base64url to standard base64 first.
    const standardBase64 = standard.replace(/-/g, '+').replace(/_/g, '/');
    const json = decodeBase64(standardBase64);
    return JSON.parse(json);
}

/**
 * Pure JavaScript base64 decoder (venera runtime lacks atob).
 * Decodes base64 to byte characters for JSON parsing.
 */
function decodeBase64(str) {
    const chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    str = str.replace(/=+$/, "");

    let result = "";
    let i = 0;
    while (i < str.length) {
        const enc1 = chars.indexOf(str.charAt(i));
        const enc2 = chars.indexOf(str.charAt(i + 1));
        const enc3 = str.charAt(i + 2) ? chars.indexOf(str.charAt(i + 2)) : -1;
        const enc4 = str.charAt(i + 3) ? chars.indexOf(str.charAt(i + 3)) : -1;

        if (enc1 < 0 || enc2 < 0) {
            throw "Invalid base64 character";
        }

        result += String.fromCharCode((enc1 << 2) | (enc2 >> 4));
        if (enc3 >= 0) {
            result += String.fromCharCode(((enc2 & 15) << 4) | (enc3 >> 2));
        }
        if (enc4 >= 0) {
            result += String.fromCharCode(((enc3 & 3) << 6) | enc4);
        }

        i += 4;
    }
    return result;
}

/** @type {import('./_venera_.js')} */
class Goda extends ComicSource {
  // Note: The fields which are marked as [Optional] should be removed if not used

  // name of the source
  name = "GoDa漫画"

  // unique id of the source
  key = "goda"

  version = "1.1.0"

  minAppVersion = "1.4.0"

  // update url
  url = "https://cdn.jsdelivr.net/gh/venera-app/venera-configs@main/goda.js"

  settings = {
    domains: {
      title: "域名",
      type: "input",
      default: "godamh.com"
    },
    api: {
      title: "API域名",
      type: "input",
      default: "api-get-v3.mgsearcher.com"
    },
    image: {
      title: "图片域名",
      type: "input",
      default: "f40-1-4.g-mh.online"
    }
  }

  get baseUrl() {
    return `https://${this.loadSetting("domains")}`;
  }

  get apiUrl() {
    return `https://${this.loadSetting("api")}/api`;
  }

  get imageUrl() {
    return `https://${this.loadSetting("image")}`;
  }

  get headers() {
    return {
      "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:144.0) Gecko/20100101 Firefox/144.0",
      "Referer": this.baseUrl
    };
  }

  parseComics(doc) {
    const result = [];
    for (let item of doc.querySelectorAll(".pb-2")) {
      const link = item.querySelector("a");
      const titleEl = item.querySelector("h3");
      const img = item.querySelector("img");
      if (link && titleEl && img && link.attributes["href"] && img.attributes["src"]) {
        result.push(new Comic({
          id: link.attributes["href"],
          title: titleEl.text,
          cover: img.attributes["src"]
        }));
      }
    }
    return result;
  }

  // explore page list
  explore = [
    {
      // title of the page.
      // title is used to identify the page, it should be unique
      title: this.name,

      /// multiPartPage or multiPageComicList or mixed
      type: "multiPartPage",

      load: async () => {
        const res = await Network.get(this.baseUrl, this.headers);
        const document = new HtmlDocument(res.body);
        const result = [{ title: "近期更新", comics: [], viewMore: null }];
        for (let item of document.querySelector(".pb-unit-md").querySelectorAll(".slicarda")) {
          result[0].comics.push(new Comic({
            id: item.attributes["href"],
            title: item.querySelector("h3").text,
            cover: item.querySelector("img").attributes["src"]
          }))
        }
        const cardlists = document.querySelectorAll(".cardlist");
        const hometitles = document.querySelectorAll(".hometitle");
        for (let i = 0; i < hometitles.length; i++) {
          result.push({
            title: hometitles[i].querySelector("h2").text,
            comics: this.parseComics(cardlists[i]),
            viewMore: {
              page: "category",
              attributes: {
                category: hometitles[i].querySelector("h2").text,
                param: hometitles[i].attributes["href"]
              },
            }
          });
        }
        return result;
      }
    }
  ]

  // categories
  category = {
    /// title of the category page, used to identify the page, it should be unique
    title: this.name,
    parts: [
      {
        name: "类型",
        type: "fixed",
        categories: [
          "全部",
          "韩漫",
          "热门漫画",
          "国漫",
          "其他",
          "日漫",
          "欧美"
        ],
        itemType: "category",
        categoryParams: [
          "/manga",
          "/manga-genre/kr",
          "/manga-genre/hots",
          "/manga-genre/cn",
          "/manga-genre/qita",
          "/manga-genre/jp",
          "/manga-genre/ou-mei"
        ],
      },
      {
        name: "标签",
        type: "fixed",
        categories: [
          "复仇",
          "古风",
          "奇幻",
          "逆袭",
          "异能",
          "宅向",
          "穿越",
          "热血",
          "纯爱",
          "系统",
          "重生",
          "冒险",
          "灵异",
          "大女主",
          "剧情",
          "恋爱",
          "玄幻",
          "女神",
          "科幻",
          "魔幻",
          "推理",
          "猎奇",
          "治愈",
          "都市",
          "异形",
          "青春",
          "末日",
          "悬疑",
          "修仙",
          "战斗"
        ],
        itemType: "category",
        categoryParams: [
          "/manga-tag/fuchou",
          "/manga-tag/gufeng",
          "/manga-tag/qihuan",
          "/manga-tag/nixi",
          "/manga-tag/yineng",
          "/manga-tag/zhaixiang",
          "/manga-tag/chuanyue",
          "/manga-tag/rexue",
          "/manga-tag/chunai",
          "/manga-tag/xitong",
          "/manga-tag/zhongsheng",
          "/manga-tag/maoxian",
          "/manga-tag/lingyi",
          "/manga-tag/danvzhu",
          "/manga-tag/juqing",
          "/manga-tag/lianai",
          "/manga-tag/xuanhuan",
          "/manga-tag/nvshen",
          "/manga-tag/kehuan",
          "/manga-tag/mohuan",
          "/manga-tag/tuili",
          "/manga-tag/lieqi",
          "/manga-tag/zhiyu",
          "/manga-tag/doushi",
          "/manga-tag/yixing",
          "/manga-tag/qingchun",
          "/manga-tag/mori",
          "/manga-tag/xuanyi",
          "/manga-tag/xiuxian",
          "/manga-tag/zhandou"
        ],
      }
    ],
    // enable ranking page
    enableRankingPage: false,
  }

  /// category comic loading related
  categoryComics = {
    load: async (category, params, options, page) => {
      const res = await Network.get(`${this.baseUrl}${params}/page/${page}`, this.headers);
      if (res.status !== 200) {
        throw `Invalid status code: ${res.status}`;
      }
      const document = new HtmlDocument(res.body);
      let maxPage = null;
      try {
        maxPage = parseInt(document.querySelectorAll("button.text-small").pop().text.replaceAll("\n", "").replaceAll(" ", ""));
      } catch(_) {
        maxPage = 1;
      }
      return {
        comics: this.parseComics(document),
        maxPage: maxPage
      };
    }
  }

  /// search related
  search = {
    load: async (keyword, options, page) => {
      const res = await Network.get(`${this.baseUrl}/s/${keyword}?page=${page}`);
      if (res.status !== 200) {
        throw `Invalid status code: ${res.status}`;
      }
      const document = new HtmlDocument(res.body);
      let maxPage = null;
      try {
        maxPage = parseInt(document.querySelectorAll("button.text-small").pop().text.replaceAll("\n", "").replaceAll(" ", ""));
      } catch(_) {
        maxPage = 1;
      }
      return {
        comics: this.parseComics(document),
        maxPage: maxPage
      };
    },
    // enable tags suggestions
    enableTagsSuggestions: false,
  }

  /// single comic related
  comic = {
    onThumbnailLoad: (url) => {
      return {
        headers: this.headers
      }
    },
    loadInfo: async (id) => {
      const res = await Network.get(this.baseUrl + id);
      if (res.status !== 200) {
        throw `Invalid status code: ${res.status}`;
      }
      const document = new HtmlDocument(res.body);

      const titleEl = document.querySelector(".text-xl");
      const title = titleEl ? (titleEl.text || "").trim().split("   ")[0] : "";

      const coverEl = document.querySelector(".object-cover");
      const cover = (coverEl && coverEl.attributes && coverEl.attributes["src"]) || "";

      const descEl = document.querySelector("p.text-medium");
      const description = descEl ? (descEl.text || "") : "";

      const infos = document.querySelectorAll("div.py-1");
      const tags = { "作者": [], "类型": [], "标签": [] };
      if (infos && infos.length >= 3) {
        if (infos[0]) {
          for (let author of infos[0].querySelectorAll("a > span")) {
            let author_name = (author.text || "").trim();
            if (author_name.endsWith(",")) {
              author_name = author_name.slice(0, -1).trim();
            }
            if (author_name) tags["作者"].push(author_name);
          }
        }
        if (infos[1]) {
          for (let category of infos[1].querySelectorAll("a > span")) {
            let category_name = (category.text || "").trim();
            if (category_name.endsWith(",")) {
              category_name = category_name.slice(0, -1).trim();
            }
            if (category_name) tags["类型"].push(category_name);
          }
        }
        if (infos[2]) {
          for (let tag of infos[2].querySelectorAll("a")) {
            const tagText = (tag.text || "").replace("\n", "").replaceAll(" ", "").replace("#", "");
            if (tagText) tags["标签"].push(tagText);
          }
        }
      }

      const mangaEl = document.querySelector("#mangachapters");
      const mangaId = mangaEl && mangaEl.attributes ? mangaEl.attributes["data-mid"] : null;
      if (!mangaId) {
        throw "无法获取漫画ID";
      }

      const jsonRes = await Network.get(`${this.apiUrl}/manga/get?mid=${mangaId}&mode=all&t=${Date.now()}`, this.headers);
      const jsonData = JSON.parse(jsonRes.body);
      const chapters = {};
      if (jsonData["data"] && jsonData["data"]["chapters"]) {
        for (let ch of jsonData["data"]["chapters"]) {
          if (ch["id"] != null && ch["attributes"] && ch["attributes"]["title"] != null) {
            chapters[`${mangaId}@${ch["id"]}`] = ch["attributes"]["title"];
          }
        }
      }
      const recommend = [];
      for (let item of document.querySelectorAll("div.cardlist > div.pb-2")) {
        const recLink = item.querySelector("a");
        const recTitle = item.querySelector("h3");
        const recImg = item.querySelector("img");
        if (recLink && recTitle && recImg && recLink.attributes["href"] && recImg.attributes["src"]) {
          recommend.push(new Comic({
            id: recLink.attributes["href"],
            title: recTitle.text,
            cover: recImg.attributes["src"]
          }));
        }
      }
      return new ComicDetails({
        title: title,
        cover: cover,
        description: description,
        tags: tags,
        chapters: chapters,
        recommend: recommend,
      });
    },

    loadEp: async (comicId, epId) => {
      if (!epId || !epId.includes("@")) {
        throw "无效的章节ID";
      }
      const ids = epId.split("@");
      const res = await Network.get(`${this.apiUrl}/v2/chapter/getinfo?m=${ids[0]}&c=${ids[1]}`, this.headers);
      if (res.status !== 200) {
        throw `Invalid status code: ${res.status}`;
      }
      const jsonData = JSON.parse(res.body);
      const imagesRaw = jsonData["data"]["info"]["images"]["images"];

      let imagesList;
      if (typeof imagesRaw === "string") {
        // v2 API: obfuscated string - decode it back to JSON array
        imagesList = decodeChapterImages(imagesRaw);
      } else {
        // v1 API (backward compatibility): array of {url: "...", order: N}
        imagesList = imagesRaw;
      }

      const images = [];
      for (let i of imagesList) {
        if (i && i["url"]) {
          images.push(this.imageUrl + i["url"]);
        }
      }
      return { images };
    },

    // enable tags translate
    enableTagsTranslate: false,
  }
}
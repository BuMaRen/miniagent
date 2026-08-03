#!/usr/bin/env python3
"""抽取番茄小说 (fanqienovel.com) 各类型排行榜,统计出当日最热门的小说类型。

原理:
- /rank 首页服务端渲染的 window.__INITIAL_STATE__ 中带有全部类型列表
  (rank.rankCategoryTypeList,分男频/女频两组,每组若干 {id, name})。
- 每个类型的分榜页面地址形如 /rank/{gender}_{rank_list_type}_{category_id}:
    gender:          0 = 女频, 1 = 男频
    rank_list_type:  1 = 阅读榜(按当前在读人数), 2 = 新书榜
- 分榜页面同样是服务端渲染,同样嵌了 __INITIAL_STATE__,其中
  rank.book_list 是该类型 Top10 书籍,每本书带 read_count(在读人数)。
- 用 Top10 在读人数之和作为该类型的"热度",取最高者即为当日最热类型。
- 37 个排行榜类型颗粒度较粗(如"都市脑洞"),要看更细的分类需要打开具体
  某本书的详情页 /page/{book_id},其 __INITIAL_STATE__.page.categoryV2
  (JSON 字符串,需要二次 json.loads)里是该书完整的标签列表,每个标签带
  Dim(1=一级分类, 3=元素标签, 10=主题/题材标签)和 MainCategory(是否为
  该书的主分类,通常等于排行榜顶层类型)。对热度前几名类型的最热单本抓取
  这份标签,就能看到比排行榜分类更细的题材构成。

用法:
    python scripts/fanqie_hot_category.py
    python scripts/fanqie_hot_category.py --rank-list-type 2 --top 10
    python scripts/fanqie_hot_category.py --detail-count 5
    python scripts/fanqie_hot_category.py --json-out today.json
"""

import argparse
import json
import re
import sys
import time
from datetime import date

import requests

BASE_URL = "https://fanqienovel.com"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}
STATE_MARKER = "window.__INITIAL_STATE__="
# 页面用 JS 对象字面量拼出该状态,个别字段会是裸的 undefined(合法 JS,非法 JSON)
_BARE_UNDEFINED_RE = re.compile(r"(?<=:)undefined\b")


def _extract_braced_object(text: str, start: int) -> str:
    """从 start(首个 '{' 处)按引号感知的括号计数,取出完整的花括号对象。"""
    depth = 0
    in_str = False
    esc = False
    quote = None
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == quote:
                in_str = False
        else:
            if c in ('"', "'"):
                in_str = True
                quote = c
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]
    raise RuntimeError("未找到匹配的花括号结尾")


def fetch_initial_state(path: str) -> dict:
    resp = requests.get(BASE_URL + path, headers=HEADERS, timeout=10)
    resp.raise_for_status()
    html = resp.text
    idx = html.find(STATE_MARKER)
    if idx == -1:
        raise RuntimeError(f"页面中未找到 __INITIAL_STATE__: {path}")
    start = idx + len(STATE_MARKER)
    raw = _extract_braced_object(html, start)
    raw = _BARE_UNDEFINED_RE.sub("null", raw)
    return json.loads(raw)


def get_categories() -> list[dict]:
    data = fetch_initial_state("/rank")
    cat_lists = data["rank"]["rankCategoryTypeList"]
    categories = []
    for gender_name, gender_code in (("female", 0), ("male", 1)):
        for c in cat_lists.get(gender_name, []):
            categories.append({
                "gender": gender_code,
                "gender_name": "女频" if gender_code == 0 else "男频",
                "category_id": c["id"],
                "name": c["name"],
            })
    return categories


def fetch_category_books(category: dict, rank_list_type: int) -> list[dict]:
    path = f"/rank/{category['gender']}_{rank_list_type}_{category['category_id']}"
    data = fetch_initial_state(path)
    book_list = data.get("rank", {}).get("book_list") or []
    books = []
    for b in book_list:
        try:
            read_count = int(b.get("read_count") or 0)
        except (TypeError, ValueError):
            read_count = 0
        try:
            word_count = int(b.get("wordNumber") or 0)
        except (TypeError, ValueError):
            word_count = 0
        books.append({
            "book_id": b.get("bookId"),
            "name": b.get("bookName"),
            "author": b.get("author"),
            "read_count": read_count,
            "word_count": word_count,
        })
    return books


def fetch_book_tags(book_id: str) -> list[dict]:
    """抓取书籍详情页 (/page/{book_id}),解析出细分类/标签 (categoryV2)。

    categoryV2 里每个 tag 有 Dim(维度: 1=一级分类, 3=元素标签, 10=主题/题材标签)
    和 MainCategory(是否为该书的主分类,通常就等于排行榜的顶层类型)。
    """
    data = fetch_initial_state(f"/page/{book_id}")
    raw_tags = data.get("page", {}).get("categoryV2")
    if not raw_tags:
        return []
    if isinstance(raw_tags, str):
        raw_tags = json.loads(raw_tags)
    return [
        {
            "name": t.get("Name"),
            "dim": t.get("Dim"),
            "is_main": bool(t.get("MainCategory")),
            "desc": t.get("ExternalDesc"),
        }
        for t in raw_tags
    ]


def main():
    parser = argparse.ArgumentParser(description="抽取番茄小说每日最热类型")
    parser.add_argument("--rank-list-type", type=int, default=1, choices=[1, 2],
                         help="1=阅读榜(默认,按在读人数) 2=新书榜")
    parser.add_argument("--delay", type=float, default=0.8,
                         help="每次请求之间的间隔秒数,避免过于频繁请求(默认 0.8)")
    parser.add_argument("--top", type=int, default=5, help="打印热度前 N 的类型(默认 5)")
    parser.add_argument("--detail-count", type=int, default=3,
                         help="对热度前 N 的类型,抓取其最热单本的详细分类/标签(默认 3,0 表示不抓取)")
    parser.add_argument("--max-words", type=int, default=None,
                         help="只统计字数不超过该值的作品(如 50000 表示 5 万字以内);不设置则不过滤")
    parser.add_argument("--json-out", type=str, default=None,
                         help="将完整结果保存为 JSON 文件的路径")
    args = parser.parse_args()

    print("正在获取类型列表 ...", file=sys.stderr)
    categories = get_categories()
    print(f"共 {len(categories)} 个类型,开始抓取各类型排行榜 ...", file=sys.stderr)

    results = []
    for i, cat in enumerate(categories, 1):
        try:
            books = fetch_category_books(cat, args.rank_list_type)
        except Exception as e:
            print(f"  [{i}/{len(categories)}] {cat['name']} 抓取失败: {e}", file=sys.stderr)
            continue
        fetched_count = len(books)
        if args.max_words is not None:
            books = [b for b in books if b["word_count"] <= args.max_words]
        total_read = sum(b["read_count"] for b in books)
        top_book = max(books, key=lambda b: b["read_count"], default=None)
        results.append({
            **cat,
            "total_read_count": total_read,
            "book_count": len(books),
            "fetched_count": fetched_count,
            "top_book": top_book,
        })
        filter_note = (
            f"(字数<={args.max_words} 的有 {len(books)}/{fetched_count} 本) "
            if args.max_words is not None else ""
        )
        print(f"  [{i}/{len(categories)}] {cat['gender_name']}-{cat['name']}: "
              f"{filter_note}在读总数 {total_read:,}", file=sys.stderr)
        if i < len(categories):
            time.sleep(args.delay)

    results.sort(key=lambda r: r["total_read_count"], reverse=True)

    today = date.today().isoformat()
    rank_type_text = "阅读榜" if args.rank_list_type == 1 else "新书榜"
    words_note = f",字数<={args.max_words}" if args.max_words is not None else ""
    print(f"\n===== {today} 番茄小说 {rank_type_text} 类型热度排行(Top {args.top}{words_note}) =====")
    for i, r in enumerate(results[: args.top], 1):
        top_book = r["top_book"]
        top_book_text = (
            f"《{top_book['name']}》({top_book['read_count']:,} 人在读,{top_book['word_count']:,} 字)"
            if top_book else "无符合条件作品"
        )
        print(f"{i}. {r['gender_name']} {r['name']:<8} "
              f"符合条件 {r['book_count']} 本  在读总数: {r['total_read_count']:>10,}  最热单本: {top_book_text}")

    if results:
        hottest = results[0]
        print(f"\n>>> 今日最热类型: {hottest['gender_name']} - {hottest['name']} <<<")

    if args.detail_count > 0:
        print(f"\n===== 热度前 {min(args.detail_count, len(results))} 类型 · 最热单本的细分类 =====")
        for r in results[: args.detail_count]:
            top_book = r["top_book"]
            if not top_book or not top_book.get("book_id"):
                continue
            try:
                tags = fetch_book_tags(top_book["book_id"])
            except Exception as e:
                print(f"  {r['name']} -《{top_book['name']}》标签抓取失败: {e}", file=sys.stderr)
                continue
            top_book["tags"] = tags
            main_tags = [t["name"] for t in tags if t["is_main"]]
            sub_tags = [t["name"] for t in tags if not t["is_main"]]
            print(f"\n【{r['gender_name']}-{r['name']}】《{top_book['name']}》"
                  f"({top_book['read_count']:,} 人在读)")
            print(f"  主分类: {'、'.join(main_tags) or 'N/A'}")
            print(f"  细分标签: {'、'.join(sub_tags) or 'N/A'}")
            time.sleep(args.delay)

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(
                {"date": today, "rank_list_type": args.rank_list_type, "results": results},
                f, ensure_ascii=False, indent=2,
            )
        print(f"\n完整结果已保存到 {args.json_out}")


if __name__ == "__main__":
    main()

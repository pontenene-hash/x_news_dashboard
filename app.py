from __future__ import annotations

import html
import json
import os
import re
from datetime import timezone
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import feedparser
import streamlit as st
from google import genai


APP_TITLE = "X投稿ネタ｜最新ニュース収集ダッシュボード"
MAX_ARTICLES = 5
REQUEST_TIMEOUT_SECONDS = 15
GEMINI_MODEL = "gemini-3.5-flash-lite"
RSS_PRESETS = {
    "Yahoo!ニュース｜主要": "https://news.yahoo.co.jp/rss/topics/top-picks.xml",
    "Yahoo!ニュース｜国内": "https://news.yahoo.co.jp/rss/topics/domestic.xml",
    "Yahoo!ニュース｜国際": "https://news.yahoo.co.jp/rss/topics/world.xml",
    "Yahoo!ニュース｜経済": "https://news.yahoo.co.jp/rss/topics/business.xml",
    "Yahoo!ニュース｜エンタメ": "https://news.yahoo.co.jp/rss/topics/entertainment.xml",
    "Yahoo!ニュース｜スポーツ": "https://news.yahoo.co.jp/rss/topics/sports.xml",
    "Yahoo!ニュース｜IT": "https://news.yahoo.co.jp/rss/topics/it.xml",
    "Yahoo!ニュース｜科学": "https://news.yahoo.co.jp/rss/topics/science.xml",
    "その他のRSSを自分で入力": "",
}
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36 RSS-News-Dashboard/1.0"
)


st.set_page_config(
    page_title="X投稿ネタ収集ダッシュボード",
    page_icon="📰",
    layout="centered",
)


st.markdown(
    """
    <style>
    .block-container {
        max-width: 900px;
        padding-top: 2.3rem;
        padding-bottom: 4rem;
    }
    .hero {
        padding: 1.8rem 1.9rem;
        margin-bottom: 1.5rem;
        border-radius: 22px;
        color: white;
        background: linear-gradient(135deg, #111827 0%, #1d4ed8 100%);
        box-shadow: 0 14px 35px rgba(29, 78, 216, 0.18);
    }
    .hero h1 {
        margin: 0 0 0.45rem 0;
        font-size: clamp(1.7rem, 5vw, 2.35rem);
        line-height: 1.25;
    }
    .hero p {
        margin: 0;
        color: #dbeafe;
        line-height: 1.7;
    }
    .news-card {
        background: #ffffff;
        border: 1px solid #e5e7eb;
        border-left: 5px solid #2563eb;
        border-radius: 16px;
        padding: 1.25rem 1.35rem;
        margin: 1rem 0;
        box-shadow: 0 7px 22px rgba(15, 23, 42, 0.07);
    }
    .news-number {
        display: inline-block;
        margin-bottom: 0.6rem;
        padding: 0.2rem 0.65rem;
        border-radius: 999px;
        background: #dbeafe;
        color: #1d4ed8;
        font-size: 0.76rem;
        font-weight: 700;
    }
    .news-title {
        margin: 0 0 0.5rem 0;
        color: #111827;
        font-size: 1.2rem;
        line-height: 1.55;
    }
    .news-date {
        margin-bottom: 0.8rem;
        color: #64748b;
        font-size: 0.86rem;
    }
    .news-description {
        margin: 0 0 1rem 0;
        color: #334155;
        line-height: 1.8;
    }
    .news-link {
        display: inline-block;
        color: #1d4ed8 !important;
        font-weight: 700;
        text-decoration: none !important;
    }
    .news-link:hover { text-decoration: underline !important; }
    .feed-caption {
        color: #64748b;
        margin: 0.2rem 0 1.2rem 0;
        font-size: 0.92rem;
    }
    .posts-heading {
        margin: 1.2rem 0 0.4rem 0;
        color: #0f172a;
        font-size: 1.05rem;
        font-weight: 800;
    }
    .post-label {
        margin: 0.9rem 0 0.25rem 0;
        color: #334155;
        font-size: 0.92rem;
        font-weight: 700;
    }
    .char-count {
        margin: -0.35rem 0 0.75rem 0;
        color: #64748b;
        font-size: 0.78rem;
        text-align: right;
    }
    div.stButton > button {
        min-height: 3rem;
        border: 0;
        border-radius: 12px;
        color: white;
        background: #2563eb;
        font-weight: 700;
    }
    div.stButton > button:hover {
        color: white;
        background: #1d4ed8;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def is_valid_http_url(value: str) -> bool:
    """Return True only for complete HTTP(S) URLs."""
    parsed = urlparse(value.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def plain_text(value: str | None, max_length: int = 500) -> str:
    """Remove RSS-provided HTML and return a compact, safe summary."""
    if not value:
        return "概要はありません。"
    without_tags = re.sub(r"<[^>]+>", " ", value)
    normalized = re.sub(r"\s+", " ", html.unescape(without_tags)).strip()
    if not normalized:
        return "概要はありません。"
    if len(normalized) > max_length:
        return normalized[: max_length - 1].rstrip() + "…"
    return normalized


def format_published_date(entry: feedparser.FeedParserDict) -> str:
    """Prefer the feed's displayed date and provide a stable fallback."""
    raw_date = entry.get("published") or entry.get("updated")
    if not raw_date:
        return "公開日時：情報なし"

    try:
        parsed = parsedate_to_datetime(raw_date)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        japan_time = parsed.astimezone(ZoneInfo("Asia/Tokyo"))
        return f"公開日時：{japan_time.strftime('%Y年%m月%d日 %H:%M JST')}"
    except (TypeError, ValueError, OverflowError):
        return f"公開日時：{raw_date}"


def article_from_entry(entry: feedparser.FeedParserDict) -> dict[str, object]:
    """Convert feedparser data into session-safe plain Python values."""
    return {
        "title": plain_text(entry.get("title"), max_length=180),
        "link": str(entry.get("link") or "").strip(),
        "description": plain_text(entry.get("description") or entry.get("summary")),
        "published": format_published_date(entry),
        "posts": None,
    }


def normalize_post(post: str, fallback_tags: tuple[str, str]) -> str:
    """Keep exactly two hashtags and fit the finished post within 140 chars."""
    compact = re.sub(r"\s+", " ", str(post)).strip().strip('"')
    hashtags = re.findall(r"#[^\s#]+", compact)
    body = re.sub(r"#[^\s#]+", "", compact)
    body = re.sub(r"\s+", " ", body).strip()

    unique_tags: list[str] = []
    for tag in [*hashtags, *fallback_tags]:
        if tag not in unique_tags:
            unique_tags.append(tag)
        if len(unique_tags) == 2:
            break

    suffix = " ".join(unique_tags)
    body_limit = 140 - len(suffix) - 1
    if len(body) > body_limit:
        body = body[: max(1, body_limit - 1)].rstrip("、。,. ") + "…"
    return f"{body} {suffix}".strip()


def parse_generated_posts(raw_text: str, article_count: int) -> list[dict[str, str]]:
    """Parse the model's JSON response and normalize every post."""
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end < start:
        raise ValueError("LLMの回答をJSONとして読み取れませんでした。")

    data = json.loads(cleaned[start : end + 1])
    items = data.get("articles")
    if not isinstance(items, list) or len(items) < article_count:
        raise ValueError("LLMから必要な数の投稿案が返されませんでした。")

    indexed = {int(item.get("index", 0)): item for item in items if isinstance(item, dict)}
    results: list[dict[str, str]] = []
    for index in range(1, article_count + 1):
        item = indexed.get(index)
        if not item:
            raise ValueError(f"ニュース{index}の投稿案が見つかりませんでした。")
        results.append(
            {
                "pattern_a": normalize_post(item.get("pattern_a", ""), ("#ニュース解説", "#最新情報")),
                "pattern_b": normalize_post(item.get("pattern_b", ""), ("#知っておきたい", "#ニュース")),
                "pattern_c": normalize_post(item.get("pattern_c", ""), ("#私の意見", "#ニュース")),
            }
        )
    return results


def generate_posts_for_articles(
    articles: list[dict[str, object]], api_key: str, experience_memo: str
) -> list[dict[str, str]]:
    """Generate three X post variants per article with one Gemini request."""
    news_material = []
    for index, article in enumerate(articles, start=1):
        news_material.append(
            {
                "index": index,
                "title": article["title"],
                "description": article["description"],
                "published": article["published"],
            }
        )

    memo_instruction = (
        f"以下は利用者本人が入力した経験・意見です。関連する場合だけパターンCに自然に反映してください。"
        f"入力されていない事実は絶対に作らないでください。\n{experience_memo.strip()}"
        if experience_memo.strip()
        else "本人の経験メモはありません。パターンCでは架空の経験を作らず、『自分はこう思う』という意見表現だけを使ってください。"
    )

    prompt = f"""
あなたは日本語のX（Twitter）運用に強いSNS編集者です。
下記のニュースごとに、投稿テキストを3パターン作成してください。

【パターンA：専門家による解説】
ニュースの背景や今後の影響を論理的に解説する、知的で落ち着いたトーン。

【パターンB：初心者への警鐘・アドバイス】
「これを知らないと損をする」という切り口で、過度に煽らず、注意喚起と具体的な行動を促すトーン。

【パターンC：個人の共感・オピニオン】
「自分はこう思う」という感情や共感が伝わる、人間味のあるトーン。

厳守事項：
- 各投稿は本文とハッシュタグを合わせて日本語140文字以内、できるだけ130〜140文字にする。
- 各投稿の末尾に、内容に合うハッシュタグを半角#で必ず2個だけ付ける。
- URLは投稿に含めない。
- 提供されたタイトルと概要にない数字・固有名詞・事実を作らない。
- 同じ言い回しを3パターンで繰り返さない。
- 前置きやMarkdownを付けず、指定のJSONだけを返す。

{memo_instruction}

出力形式：
{{"articles":[{{"index":1,"pattern_a":"...","pattern_b":"...","pattern_c":"..."}}]}}

ニュース資料：
{json.dumps(news_material, ensure_ascii=False)}
""".strip()

    client = genai.Client(api_key=api_key)
    interaction = client.interactions.create(model=GEMINI_MODEL, input=prompt)
    if not interaction.output_text:
        raise ValueError("LLMから投稿案が返されませんでした。")
    return parse_generated_posts(interaction.output_text, len(articles))


@st.cache_data(ttl=300, show_spinner=False)
def fetch_feed(feed_url: str) -> feedparser.FeedParserDict:
    """Download an RSS/Atom feed and parse it. Results are cached for 5 min."""
    request = Request(
        feed_url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/atom+xml, text/xml, */*"},
    )
    with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        content = response.read()

    parsed_feed = feedparser.parse(content)
    if parsed_feed.bozo and not parsed_feed.entries:
        raise ValueError(f"RSSの解析に失敗しました: {parsed_feed.bozo_exception}")
    return parsed_feed


def render_news_card(article: dict[str, object], number: int) -> None:
    title = html.escape(str(article["title"]))
    link = str(article["link"])
    safe_link = html.escape(link, quote=True)
    description = html.escape(str(article["description"]))
    published = html.escape(str(article["published"]))

    link_html = (
        f'<a class="news-link" href="{safe_link}" target="_blank" '
        'rel="noopener noreferrer">記事を開く →</a>'
        if is_valid_http_url(link)
        else '<span class="news-date">記事URLはありません</span>'
    )

    st.markdown(
        f"""
        <article class="news-card">
            <span class="news-number">NEWS {number}</span>
            <h2 class="news-title">{title}</h2>
            <div class="news-date">{published}</div>
            <p class="news-description">{description}</p>
            {link_html}
        </article>
        """,
        unsafe_allow_html=True,
    )

    posts = article.get("posts")
    if isinstance(posts, dict):
        labels = (
            ("pattern_a", "A｜専門家による解説"),
            ("pattern_b", "B｜初心者への警鐘・アドバイス"),
            ("pattern_c", "C｜個人の共感・オピニオン"),
        )
        st.markdown('<div class="posts-heading">✍️ AIが作成したX投稿案</div>', unsafe_allow_html=True)
        for key, label in labels:
            post = str(posts[key])
            st.markdown(f'<div class="post-label">パターン{html.escape(label)}</div>', unsafe_allow_html=True)
            st.code(post, language=None, wrap_lines=True)
            st.markdown(f'<div class="char-count">{len(post)} / 140文字</div>', unsafe_allow_html=True)


st.markdown(
    """
    <section class="hero">
        <h1>📰 X投稿ネタ収集ダッシュボード</h1>
        <p>気になるRSSフィードから最新ニュースを5件取得。X（Twitter）の投稿テーマ探しを効率化します。</p>
    </section>
    """,
    unsafe_allow_html=True,
)

try:
    saved_api_key = str(st.secrets.get("GEMINI_API_KEY", ""))
except (FileNotFoundError, KeyError):
    saved_api_key = ""
default_api_key = os.getenv("GEMINI_API_KEY", "") or saved_api_key

with st.sidebar:
    st.header("AI投稿生成の設定")
    api_key_input = st.text_input(
        "Gemini APIキー",
        value=default_api_key,
        type="password",
        help="入力したキーは画面に表示されません。",
    )
    st.markdown("[Gemini APIキーを取得する](https://aistudio.google.com/app/apikey)")
    experience_memo = st.text_area(
        "あなたの経験・意見メモ（任意）",
        placeholder="例：新しい制度への対応で、準備不足に困った経験があります。",
        help="パターンCに反映します。空欄の場合、AIは架空の経験を作りません。",
        height=130,
    )
    st.caption(f"使用モデル：{GEMINI_MODEL}")

selected_feed = st.selectbox(
    "ニュースカテゴリーを選択",
    options=list(RSS_PRESETS),
    help="Yahoo!ニュースはカテゴリーを選ぶだけでURLが入ります。ほかのサイトは「その他」を選びます。",
)

selected_url = RSS_PRESETS[selected_feed]
with st.form("rss_form"):
    feed_url = st.text_input(
        "RSSフィードのURL",
        value=selected_url,
        placeholder="https://example.com/feed/",
        help="選択したYahoo!ニュースのURLを編集することも、任意のRSS/Atom URLを入力することもできます。",
        key=f"rss_url_{selected_feed}",
    )
    submitted = st.form_submit_button("最新ニュースを取得", use_container_width=True)

if submitted:
    cleaned_url = feed_url.strip()

    if not cleaned_url:
        st.warning("RSSフィードのURLを入力してください。")
    elif not is_valid_http_url(cleaned_url):
        st.error("URLの形式を確認してください。http:// または https:// から入力します。")
    else:
        try:
            with st.spinner("最新ニュースを取得しています…"):
                feed = fetch_feed(cleaned_url)

            entries = list(feed.entries[:MAX_ARTICLES])
            if not entries:
                st.session_state.pop("articles", None)
                st.info("このRSSフィードには表示できる記事がありませんでした。")
            else:
                articles = [article_from_entry(entry) for entry in entries]
                feed_title = plain_text(feed.feed.get("title"), max_length=100)
                st.session_state["feed_title"] = feed_title if feed.feed.get("title") else ""
                st.session_state["articles"] = articles
                st.success(f"最新ニュースを{len(articles)}件取得しました。")

                if api_key_input.strip():
                    try:
                        with st.spinner(f"AIが{len(articles) * 3}本のX投稿案を作成しています…"):
                            generated = generate_posts_for_articles(
                                articles, api_key_input.strip(), experience_memo
                            )
                        for article, post_set in zip(articles, generated):
                            article["posts"] = post_set
                        st.session_state["articles"] = articles
                        st.success("3パターンのX投稿案を作成しました。")
                    except Exception as exc:
                        st.error(f"X投稿案を生成できませんでした。APIキーや利用状況をご確認ください。（{exc}）")
                else:
                    st.warning("ニュースは取得できました。左側でGemini APIキーを入力すると投稿案も生成できます。")

        except HTTPError as exc:
            st.error(f"RSSを取得できませんでした（HTTP {exc.code}）。URLや配信元の状態をご確認ください。")
        except URLError as exc:
            st.error(f"RSSに接続できませんでした。通信環境またはURLをご確認ください。（{exc.reason}）")
        except TimeoutError:
            st.error("RSSの取得がタイムアウトしました。しばらくしてから再度お試しください。")
        except ValueError as exc:
            st.error(str(exc))
        except Exception as exc:
            st.error(f"ニュースの取得中にエラーが発生しました: {exc}")

articles_in_state = st.session_state.get("articles", [])
if articles_in_state:
    feed_title_in_state = str(st.session_state.get("feed_title", ""))
    if feed_title_in_state:
        st.markdown(
            f'<p class="feed-caption">取得元：{html.escape(feed_title_in_state)}</p>',
            unsafe_allow_html=True,
        )

    needs_generation = any(not article.get("posts") for article in articles_in_state)
    if needs_generation and api_key_input.strip():
        if st.button("表示中のニュースからX投稿案を生成", use_container_width=True):
            try:
                with st.spinner(f"AIが{len(articles_in_state) * 3}本のX投稿案を作成しています…"):
                    generated = generate_posts_for_articles(
                        articles_in_state, api_key_input.strip(), experience_memo
                    )
                for article, post_set in zip(articles_in_state, generated):
                    article["posts"] = post_set
                st.session_state["articles"] = articles_in_state
                st.rerun()
            except Exception as exc:
                st.error(f"X投稿案を生成できませんでした。APIキーや利用状況をご確認ください。（{exc}）")

    for index, article in enumerate(articles_in_state, start=1):
        render_news_card(article, index)

st.caption("※ RSS配信元によって、概要や公開日時が含まれない場合があります。AIの投稿案は公開前に内容をご確認ください。")

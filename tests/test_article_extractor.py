# -*- coding: utf-8 -*-
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
from collector import NewsArticle
from article_extractor import extract_article_body, enrich_top_articles


def test_extract_article_body_success():
    fake_html = (
        "<html><head><title>Test Page</title></head><body><article>"
        "<p>这是中国央行针对货币政策发布的最新指引，旨在维护银行体系流动性合理充裕并促进综合融资成本稳中有降。</p>"
        "<p>业内权威宏观经济学家分析指出，本次适度加大逆周期调节力度的政策落地，将对制造业投资与居民消费信贷形成实质性支撑。</p>"
        "<p>在跨市场大类资产配置维度，股票市场风险溢价有望得到修复，国债收益率曲线将保持平稳健康运行态势。</p>"
        "<p>cookie policy and privacy agreement to be filtered out</p>"
        "</article></body></html>"
    ).encode("utf-8")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = fake_html
    mock_resp.headers = {"Content-Type": "text/html; charset=utf-8"}

    with patch("requests.get", return_value=mock_resp):
        body = extract_article_body("https://test.example.com/story123")
        assert body is not None
        assert "这是中国央行针对货币政策发布的最新指引" in body
        assert "cookie policy" not in body


def test_enrich_top_articles_replaces_short_summary():
    now = datetime.now(timezone.utc)
    a1 = NewsArticle(
        source="联合早报",
        title="中国官媒警告：若欧盟执意出台歧视性措施 中方有应对工具",
        url="https://www.zaobao.com.sg/news/china/story20261007-12345",
        summary="简要标题",
        published_at=now,
        relevance_score=12.0
    )
    # Google news redirect item should not be targeted
    a2 = NewsArticle(
        source="彭博社",
        title="US Lead in AI Over China Narrows",
        url="https://news.google.com/rss/articles/xyz123",
        summary="Short",
        published_at=now,
        relevance_score=15.0
    )

    articles_map = {
        "联合早报": [a1],
        "彭博社": [a2]
    }

    with patch("article_extractor.extract_article_body") as mock_extract:
        mock_extract.return_value = "这是抓取到的长篇事实正文段落，详细阐述了关税争端与反倾销调查机制。"
        count = enrich_top_articles(articles_map, top_n=5)

        assert count == 1
        assert "这是抓取到的长篇事实正文段落" in a1.summary
        # Google News item remains untouched
        assert a2.summary == "Short"

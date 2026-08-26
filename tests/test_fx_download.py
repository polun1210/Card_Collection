"""臺銀下載器的行為。

本專案的測試一律走 HTTP、在傳輸層回放錄下的回應，**這個檔案是唯一的例外**：
匯率走 curl_cffi 模擬 Chrome 的 TLS 指紋（ADR-0017），那是另一套 HTTP 堆疊，
攔不到 httpx 的傳輸層。所以這裡直接替換 curl_cffi 的 get，驗證下載器本身。
"""

import pytest
from curl_cffi import requests as curl_requests

from card_collection.fx import (
    ACCEPT_LANGUAGE,
    IMPERSONATE_TARGET,
    BotRateDownload,
    FxRateError,
)


class _Response:
    def __init__(self, status_code: int, content: bytes) -> None:
        self.status_code = status_code
        self.content = content


@pytest.fixture
def recorded_get(monkeypatch):
    """記下下載器實際送出的參數，並回傳指定的回應。"""
    calls: list[dict] = []

    def install(response=None, error: Exception | None = None):
        def fake_get(url, **kwargs):
            calls.append({"url": url, **kwargs})
            if error is not None:
                raise error
            return response

        monkeypatch.setattr(curl_requests, "get", fake_get)
        return calls

    return install


def test_模擬Chrome指紋並指定中文牌告(recorded_get):
    # Arrange：不指定語言會拿到英文版，欄位的字就對不上
    calls = recorded_get(_Response(200, b"csv"))

    # Act
    BotRateDownload()()

    # Assert
    assert calls[0]["impersonate"] == IMPERSONATE_TARGET
    assert calls[0]["headers"]["Accept-Language"] == ACCEPT_LANGUAGE


def test_成功時原樣回傳內容(recorded_get):
    # Arrange
    recorded_get(_Response(200, "﻿資料日期,body".encode("utf-8")))

    # Act
    body = BotRateDownload()()

    # Assert：解析交給 parse_bot_csv，下載器一個位元組都不動
    assert body.decode("utf-8-sig") == "資料日期,body"


def test_非200明確失敗(recorded_get):
    # Arrange
    recorded_get(_Response(503, b""))

    # Act / Assert：絕不退化成「查無匯率」
    with pytest.raises(FxRateError, match="503"):
        BotRateDownload()()


def test_連線失敗轉成匯率錯誤(recorded_get):
    # Arrange
    recorded_get(error=curl_requests.exceptions.ConnectionError("連線中斷"))

    # Act / Assert
    with pytest.raises(FxRateError, match="請求失敗"):
        BotRateDownload()()

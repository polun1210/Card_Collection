"""心跳的設定從哪裡來——只有 `from_env()` 會去讀環境變數。

`Heartbeat(url=...)` 只認明確的網址，`url=None` 的唯一意思是「明確關閉」。舊版
`__init__` 對 `None` 會 fallback 去讀環境變數，於是測試沒辦法表達「這台機器沒設定
心跳」：傳 `None` 卻拿回開發者的真實設定，測試結果因此取決於跑測試的人（issue #18）。

原本恆紅的兩條測試（`test_未設定心跳網址時完全不送`、`test_乾跑說得出心跳有沒有設定`）
會隨這次修法自動變綠，但它們沒有直接測到根因，所以這裡補上。
"""

from card_collection.heartbeat import ENV_URL, Heartbeat

FAKE_URL = "https://healthchecks.example/ping/test"


def test_明確傳None就是關閉_環境變數有設也不去讀(monkeypatch):
    # Arrange：機器上「有」設心跳網址。
    monkeypatch.setenv(ENV_URL, FAKE_URL)

    # Act：呼叫端明確表達「不要送」。
    beat = Heartbeat(url=None)

    # Assert：沒有偷偷去讀環境變數。
    assert beat.is_configured is False


def test_from_env才會去讀環境變數(monkeypatch):
    monkeypatch.setenv(ENV_URL, FAKE_URL)

    beat = Heartbeat.from_env()

    assert beat.is_configured is True


def test_環境變數是空字串時視為未設定(monkeypatch):
    monkeypatch.setenv(ENV_URL, "")

    beat = Heartbeat.from_env()

    assert beat.is_configured is False

import json
from urllib.parse import parse_qs, urlparse

import pandas as pd
import pytest

from crypto_strategy_lab.binance_data import download_klines


class Response:
    def __init__(self,payload): self.payload=payload
    def __enter__(self): return self
    def __exit__(self,*_): return False
    def read(self): return json.dumps(self.payload).encode()


def candle(timestamp,price):
    return [timestamp,str(price),str(price+1),str(price-1),str(price+.5),"10",timestamp+59_999,"0",1,"0","0","0"]


def test_download_creates_then_incrementally_updates_csv(tmp_path):
    path=tmp_path/"XRPUSDT_1m.csv"; calls=[]
    def first(request,timeout=30):
        query=parse_qs(urlparse(request.full_url).query); calls.append(query)
        return Response([candle(1_577_836_800_000,1),candle(1_577_836_860_000,2)])
    result=download_klines("xrp/usdt","1m",path,"2020-01-01","2020-01-01",opener=first)
    assert result["added"]==2 and result["total"]==2
    frame=pd.read_csv(path); assert list(frame.columns)==["timestamp","open","high","low","close","volume"]
    assert calls[0]["symbol"]==["XRPUSDT"] and calls[0]["limit"]==["1000"]

    def update(request,timeout=30):
        query=parse_qs(urlparse(request.full_url).query); assert int(query["startTime"][0])==1_577_836_920_000
        return Response([candle(1_577_836_920_000,3)])
    result=download_klines("XRPUSDT","1m",path,"2020-01-01","2020-01-01",opener=update)
    assert result["added"]==1 and result["total"]==3
    assert pd.read_csv(path)["timestamp"].is_unique


def test_download_does_not_replace_existing_file_when_cancelled(tmp_path):
    path=tmp_path/"BTCUSDT_1m.csv"; path.write_text("timestamp,open,high,low,close,volume\n100,1,1,1,1,1\n")
    try:
        download_klines("BTCUSDT","1m",path,"2020-01-01","2020-01-01",cancelled=lambda:True)
    except InterruptedError:
        pass
    assert path.read_text()=="timestamp,open,high,low,close,volume\n100,1,1,1,1,1\n"


def test_cancelled_download_resumes_from_persistent_checkpoint(tmp_path):
    path=tmp_path/"BTCUSDT_1m.csv"; state={"cancel":False}
    first_page=[candle(1_577_836_800_000 + minute*60_000, minute) for minute in range(1000)]
    def first(request,timeout=30):
        state["cancel"]=True
        return Response(first_page)
    with pytest.raises(InterruptedError):
        download_klines("BTCUSDT","1m",path,"2020-01-01","2020-01-02",opener=first,cancelled=lambda:state["cancel"])
    checkpoint=tmp_path/".BTCUSDT_1m.csv.download"
    assert checkpoint.exists() and len(pd.read_csv(checkpoint))==1000
    resumed=[]
    def second(request,timeout=30):
        query=parse_qs(urlparse(request.full_url).query); resumed.append(int(query["startTime"][0]))
        return Response([])
    result=download_klines("BTCUSDT","1m",path,"2020-01-01","2020-01-02",opener=second)
    assert resumed==[first_page[-1][0]+60_000]
    assert result["total"]==1000 and not checkpoint.exists()


def test_dataset_dialog_builds_both_paths_from_one_pair(tmp_path):
    qtwidgets=pytest.importorskip("PySide6.QtWidgets"); app=qtwidgets.QApplication.instance() or qtwidgets.QApplication([])
    from crypto_strategy_lab.gui.binance_dialog import BinanceDownloadDialog
    dialog=BinanceDownloadDialog(symbol="SOLUSDT",strategy_timeframe="1h",intrabar_timeframe="1m",data_folder=tmp_path)
    try:
        preview=dialog.preview.text()
        assert "SOLUSDT_1h.csv" in preview and "SOLUSDT_1m.csv" in preview
        dialog.symbol.setCurrentText("XRPUSDT")
        assert "XRPUSDT_1h.csv" in dialog.preview.text() and "SOLUSDT" not in dialog.preview.text()
    finally: dialog.close()

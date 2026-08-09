"""Non-blocking Binance strategy + intrabar dataset download dialog."""
from __future__ import annotations

from pathlib import Path
from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import *

from crypto_strategy_lab.binance_data import download_klines


class DatasetWorker(QObject):
    progress = Signal(str, int, str)
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, symbol, strategy_tf, intrabar_tf, include_intrabar, folder, start, end):
        super().__init__(); self.args=(symbol,strategy_tf,intrabar_tf,include_intrabar,Path(folder),start,end); self.cancelled=False

    @Slot()
    def run(self):
        symbol,strategy_tf,intrabar_tf,include_intrabar,folder,start,end=self.args
        try:
            results={}
            jobs=[("strategy",strategy_tf)]
            if include_intrabar and intrabar_tf != strategy_tf: jobs.append(("intrabar",intrabar_tf))
            elif include_intrabar: results["intrabar_same_as_strategy"]=True
            for role,timeframe in jobs:
                path=folder/f"{symbol}_{timeframe}.csv"
                results[role]=download_klines(symbol,timeframe,path,start,end,progress=lambda count,date,r=role:self.progress.emit(r,count,date),cancelled=lambda:self.cancelled)
            if include_intrabar and results.get("intrabar_same_as_strategy"):
                results["intrabar"]=results["strategy"]
            self.finished.emit(results)
        except InterruptedError:
            self.failed.emit("Download cancelled. Completed pages were saved and the next download will resume from that checkpoint.")
        except Exception as exc:
            self.failed.emit(str(exc))


class BinanceDownloadDialog(QDialog):
    def __init__(self,parent=None,*,symbol="XRPUSDT",strategy_timeframe="1h",intrabar_timeframe="1m",use_intrabar=True,data_folder="data"):
        super().__init__(parent); self.setWindowTitle("Download / Update Binance Dataset"); self.resize(620,330); self.result_data=None; self.thread=None; self.worker=None
        form=QFormLayout(self)
        note=QLabel("Downloads one matched Binance Spot dataset. You can close this window and continue running backtests while it downloads. Completed pages are checkpointed, so cancellation or application shutdown can resume later."); note.setWordWrap(True); form.addRow(note)
        self.symbol=QComboBox(); self.symbol.setEditable(True); self.symbol.addItems(["BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT"]); self.symbol.setCurrentText(symbol)
        self.strategy_tf=QComboBox(); self.strategy_tf.addItems(["1m","5m","15m","30m","1h","4h","1d"]); self.strategy_tf.setCurrentText(strategy_timeframe)
        self.include_intrabar=QCheckBox("Download matching intrabar data"); self.include_intrabar.setChecked(use_intrabar)
        self.intrabar_tf=QComboBox(); self.intrabar_tf.addItems(["1m","5m","15m","30m","1h","4h"]); self.intrabar_tf.setCurrentText(intrabar_timeframe)
        self.start=QLineEdit(); self.start.setPlaceholderText("Blank = earliest candle available for this pair")
        self.end=QLineEdit(); self.end.setPlaceholderText("Blank = latest completed candle")
        self.folder=QLineEdit(str(Path(data_folder).resolve())); browse=QPushButton("Browse"); browse.clicked.connect(self._browse); folder_row=QHBoxLayout(); folder_row.addWidget(self.folder); folder_row.addWidget(browse)
        for label,widget in (("Trading Pair",self.symbol),("Strategy Timeframe",self.strategy_tf),("",self.include_intrabar),("Intrabar Timeframe",self.intrabar_tf),("Start Date",self.start),("End Date",self.end),("Data Folder",folder_row)): form.addRow(label,widget)
        self.preview=QLabel(); self.preview.setWordWrap(True); form.addRow("Files",self.preview)
        self.status=QLabel("Ready"); self.status.setWordWrap(True); form.addRow("Status",self.status)
        buttons=QDialogButtonBox(); self.download=buttons.addButton("Download / Update Dataset",QDialogButtonBox.AcceptRole); self.cancel=buttons.addButton(QDialogButtonBox.Cancel); form.addRow(buttons)
        self.download.clicked.connect(self._start); self.cancel.clicked.connect(self._cancel); self.include_intrabar.toggled.connect(self._update); self.symbol.currentTextChanged.connect(self._update); self.strategy_tf.currentTextChanged.connect(self._update); self.intrabar_tf.currentTextChanged.connect(self._update); self.folder.textChanged.connect(self._update); self._update()

    def _update(self):
        self.intrabar_tf.setEnabled(self.include_intrabar.isChecked())
        symbol=self.symbol.currentText().strip().upper().replace("/",""); folder=Path(self.folder.text() or ".")
        files=[str(folder/f"{symbol}_{self.strategy_tf.currentText()}.csv")]
        if self.include_intrabar.isChecked(): files.append(str(folder/f"{symbol}_{self.intrabar_tf.currentText()}.csv"))
        self.preview.setText("\n".join(files))

    def _browse(self):
        folder=QFileDialog.getExistingDirectory(self,"Select candle-data folder",self.folder.text())
        if folder: self.folder.setText(folder)

    def _set_running(self,running):
        for widget in (self.symbol,self.strategy_tf,self.include_intrabar,self.intrabar_tf,self.start,self.end,self.folder,self.download): widget.setEnabled(not running)
        self.cancel.setText("Cancel Download" if running else "Close")

    def _start(self):
        symbol=self.symbol.currentText().strip().upper().replace("/","")
        if not symbol or not symbol.isalnum(): QMessageBox.warning(self,"Invalid Pair","Enter a Binance pair such as XRPUSDT."); return
        self._set_running(True); self.status.setText("Connecting to Binance…")
        self.thread=QThread(self); self.worker=DatasetWorker(symbol,self.strategy_tf.currentText(),self.intrabar_tf.currentText(),self.include_intrabar.isChecked(),self.folder.text(),self.start.text().strip() or None,self.end.text().strip() or None); self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run); self.worker.progress.connect(lambda role,count,date:self.status.setText(f"{role.title()}: downloaded {count:,} new candles… latest {date}")); self.worker.finished.connect(self._finished); self.worker.failed.connect(self._failed); self.worker.finished.connect(self.thread.quit); self.worker.failed.connect(self.thread.quit); self.thread.start()

    def _finished(self,result):
        self.result_data=result; messages=[]
        for role in ("strategy","intrabar"):
            if role in result: messages.append(f"{role.title()}: {result[role]['total']:,} candles ({result[role]['added']:,} new)")
        self.status.setText(" | ".join(messages)); self._set_running(False); self.download.setText("Done"); self.download.setEnabled(False); self.cancel.setText("Use Dataset")

    def _failed(self,message): self.status.setText(message); self._set_running(False)

    def _cancel(self):
        if self.worker and self.thread and self.thread.isRunning(): self.worker.cancelled=True; self.status.setText("Cancelling after the current request…")
        elif self.result_data: self.accept()
        else: self.reject()

    def closeEvent(self,event):
        if self.worker and self.thread and self.thread.isRunning():
            self.hide(); event.ignore(); return
        super().closeEvent(event)

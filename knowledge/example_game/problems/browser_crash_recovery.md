# 瀏覽器崩潰後自動復原

## 症狀
- TargetClosedError
- browser has been closed
- 頁面在操作中途被關閉

## 根本原因
長時間執行或記憶體壓力導致瀏覽器分頁被關閉，Playwright 後續操作即拋出 TargetClosedError。

## 解法
偵測到 TargetClosedError 時，重啟瀏覽器並重新登入，再從中斷點續跑。

## 狀態
已修復 ✅

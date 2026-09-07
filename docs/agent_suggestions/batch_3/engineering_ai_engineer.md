# AI Engineer 架構審查建議 — Batch 3

> 審查角色：AI/ML Engineer（專注模型部署、感知管線、學習迴路、資料基礎設施）
> 審查對象：DESIGN.md、ARCHITECTURE_DECISIONS.md（AD-1 ~ AD-10）
> 日期：2026-07-16
> 批次：Batch 3 — 架構工程組

---

## 建議 1：引入本地 OCR 作為 L1.5 感知層，降低 Vision LLM 單點依賴

### 問題

AD-2 將 Vision LLM 定為讀取 `game_state` 的唯一 ground truth。但 Vision LLM 存在：
- 非確定性輸出（同畫面兩次讀數可能不同）
- 延遲 1-5 秒 / 每次呼叫
- Token 成本與 rate limit
- 無法做可重現的數值基準測試

目前的「二次確認」機制（reread）本質上是用兩次昂貴的非確定性呼叫來交叉驗證，而非引入獨立的確定性訊號源。

### 建議

在 detector/perceiver 層與 Vision LLM 之間，插入 **PaddleOCR** 作為 L1.5 確定性數字讀取層：

1. 對 `game_info.yaml` 中宣告的 HUD 區域（score/currency/level 的 bounding box），直接用 PaddleOCR 做數字識別
2. OCR confidence > 0.85 → 直接作為 `game_state` 數值，不呼叫 Vision
3. OCR confidence < 0.85 或區域未宣告 → 升級到 Vision LLM
4. 兩者皆有結果時做交叉驗證：一致則高信心，矛盾則標記需人工確認

**效益**：
- PaddleOCR 在 GPU 上推理 45ms/張、CPU 340ms/張，比 Vision LLM 快 10-50 倍
- 記憶體僅 450MB（vs. Vision API 的網路延遲不可控）
- 確定性輸出可作為回歸基準
- 已有遊戲 HUD OCR 的成功案例（Balatro OCR 用 PaddleOCR fine-tune 達 production 品質）

### 參考資料

- PaddleOCR vs EasyOCR vs Doctr Benchmark — 340ms/image CPU, 45ms GPU, 450MB idle memory：https://tildalice.io/paddleocr-easyocr-doctr-memory-latency-benchmark/
- PaddleOCR vs EasyOCR 初始化與記憶體對比：https://tildalice.io/paddleocr-vs-easyocr-benchmark/
- Balatro 遊戲 HUD OCR（PaddleOCR fine-tune 實例）：https://huggingface.co/marco-costa-ml/balatro-ocr
- 遊戲文字 OCR 訓練實踐（EasyOCR baseline → CRNN 81.6% accuracy）：https://www.besthub.dev/articles/learning-ocr-for-game-text-recognition-from-data-preparation-to-crnn-model-training-7ee5b950ce4d

### 優先級：高

---

## 建議 2：用 DINOv2 Screen Embedding 取代 SSIM 全圖比對

### 問題

AD-5 承認 SSIM 對動態畫面（魚群游動）無判別力，導致：
- screen_id 不穩定（同畫面被別名拆成多條 low 邊）
- confidence 累積失效
- 新畫面 vs. 已知畫面的判定無數學閾值依據

目前提案（perceptual hash + UI 錨點指紋）仍是手工特徵工程，對遊戲類型不泛化。

### 建議

引入 **DINOv2**（自監督 vision encoder）產生 screen embedding，搭配 **sqlite-vec** 做 nearest-neighbor 匹配：

1. 每次截圖 → DINOv2 (ViT-S/14, ONNX) 產生 384-dim embedding，延遲 <50ms（CPU ONNX）
2. 已知 screen 的 reference embedding 存入 `sqlite-vec` 的 `vec0` virtual table
3. 新截圖 embedding 做 KNN 查詢：cosine distance < 0.15 → 匹配已知 screen；> 0.3 → 確認為新畫面
4. 中間地帶 → 升級到 Vision LLM 確認

**為何 DINOv2 優於 CLIP**：
- DINOv2 在影像相似度任務上 accuracy 64% vs. CLIP 28%（DISC21 benchmark）
- DINOv2 更擅長辨識主體元素（UI 佈局），CLIP 偏重細節文字
- 兩者推理速度相當（~70 images/sec）

**為何 sqlite-vec 而非 FAISS**：
- 零依賴、單一 .db 檔案、與既有 YAML 知識庫可共存
- 3ms 查詢延遲（100K vectors）、12MB 磁碟空間
- 支援 Python/Go/Rust/WASM，未來可嵌入 edge 裝置

### 參考資料

- CLIP vs DINOv2 Visual Similarity Benchmark（DISC21 dataset, DINOv2 accuracy 64% vs CLIP 28%）：https://github.com/JayyShah/CLIP-DINO-Visual-Similarity
- Screen2Vec: Semantic Embedding of GUI Screens（CHI 2021, nearest-neighbor screen retrieval）：https://toby.li/files/li-screen2vec-chi2021.pdf
- sqlite-vec：零依賴向量搜尋 SQLite 擴展（pure C, runs anywhere）：https://github.com/asg017/sqlite-vec/
- sqlite-vec stable release 介紹（vec0 virtual table, KNN with MATCH）：https://alexgarcia.xyz/blog/2024/sqlite-vec-stable-release/index.html
- sqlite-vec vs Pinecone/Chroma 實測（3ms query, 12MB for 50K vectors）：https://dev.to/robertpelloni/sqlite-vector-search-the-dependency-free-ai-memory-stack-that-outperforms-pinecone-5d27

### 優先級：高（AD-5 的前置條件，也是建議 3 的依賴）

---

## 建議 3：引入 Curiosity-Driven Q-Learning 作為探索策略引擎

### 問題

DESIGN.md 宣稱「策略進化」但 AD-6 承認：
- 無 action→outcome 記錄
- 無 Q-value / reward signal
- 無 exploration/exploitation balance
- 每步重新問 LLM「下一步做什麼」— 這不是學習，是每次重新決策

結果：agent 可能反覆嘗試同一無效操作、無法收斂到最優路徑、探索效率低。

### 建議

實作 **WebExplor 模式**的 curiosity-driven tabular Q-learning：

1. **State** = screen_id（由建議 2 的 embedding 穩定化）
2. **Action** = element_click（從知識庫的 `known_elements` 列舉）
3. **Reward** = curiosity（新 screen 發現 +1.0、新 transition +0.5、已知 transition 衰減）
4. **Q-table** 持久化於 `knowledge/<game>/q_table.yaml`（或 sqlite）
5. **Policy** = ε-greedy，ε 隨 session 數遞減（explore → exploit）

當 Q-learning 卡住（連續 N 步無新 state）→ 升級到 Vision LLM 請求創意建議（類似 WebExplor 的 DFA-guided exploration）。

**效益**：
- 探索有記憶性：不會重複走已知死路
- 可量化覆蓋率：visited_states / total_known_states
- 成本幾乎為零：Q-table 查詢是 O(1)
- 與現有架構相容：只需在 `execute_action` 前加一層策略選擇

### 參考資料

- WebExplor: Curiosity-Driven RL for Web Testing（Q-learning + DFA guidance, 發現 3466 failures）：https://arxiv.org/pdf/2103.06018
- Augmenting Automated Game Testing with Deep RL（exploit detection, coverage maximization, difficulty eval）：https://arxiv.org/abs/2103.15819
- Adaptive Metamorphic Testing with Contextual Bandits（選擇最有效的測試變換策略）：https://doi.org/10.1016/j.jss.2020.110574
- Tetraband 實作（contextual bandit for test transformation selection）：https://github.com/HelgeS/tetraband

### 優先級：中（依賴 screen_id 穩定化，即建議 2 先完成）

---

## 建議 4：以 SQLite + sqlite-vec 作為知識庫的結構化後端

### 問題

知識庫用純 YAML 儲存座標、transition、confidence。當需要：
- AD-6 的 confidence 升降（需 counter increment/decrement + timestamp）
- AD-8 的覆蓋率統計（需 aggregation query）
- 建議 2 的 embedding 索引（需向量搜尋）
- 建議 3 的 Q-table（需快速 key-value lookup）

YAML 需要每次全檔讀寫，無法做原子更新、無法做 JOIN 查詢、無法做併發安全寫入。

### 建議

採用 **SQLite + sqlite-vec** 作為 knowledge source of truth，保留 YAML export 供人類閱讀：

```
knowledge/<game>/
├── knowledge.db          ← SQLite（source of truth）
├── knowledge.yaml        ← 自動匯出（read-only for humans）
├── systems/*.yaml        ← 靜態宣告（import 進 DB）
└── game_info.yaml        ← oracle invariants（import 進 DB）
```

Schema 設計：
- `screens` table：id, name, description, embedding (vec0), reference_screenshot_path
- `transitions` table：from_screen, to_screen, action, success_count, fail_count, last_verified, confidence
- `elements` table：screen_id, element_id, type, label, x, y, w, h
- `q_values` table：screen_id, action_id, q_value, visit_count, last_updated
- `anomalies` table：session_id, timestamp, type, severity, evidence_path

**效益**：
- 原子更新 confidence（`UPDATE transitions SET success_count = success_count + 1`）
- 即時覆蓋率查詢（`SELECT COUNT(DISTINCT screen_id) FROM transitions WHERE last_verified > ?`）
- 向量搜尋與關聯查詢同一個 DB（`sqlite-vec` + FTS5 + 一般 SQL）
- 單檔備份、零伺服器、跨平台
- 與現有 YAML 人類可讀性共存（定期 export）

### 參考資料

- sqlite-vec：零依賴向量搜尋（支援 float/int8/binary vectors）：https://github.com/asg017/sqlite-vec/
- sqlite-vec stable release（vec0 virtual table, SIMD-accelerated brute-force）：https://alexgarcia.xyz/blog/2024/sqlite-vec-stable-release/index.html
- What Is sqlite-vec?（定位、與 Chroma/pgvector/Pinecone/FAISS 比較）：https://ai-tldr.dev/learn/embeddings-vector-databases/vector-database-guides/sqlite-vec-explained/
- SQLite + Vector Search 生產實測（12MB for 50K chunks, 3ms query, 60% lower infra cost）：https://dev.to/robertpelloni/sqlite-vector-search-the-dependency-free-ai-memory-stack-that-outperforms-pinecone-5d27

### 優先級：高（資料基礎設施，是所有 ML 功能的前置條件）

---

## 建議 5：建立 Sensor Fusion Layer 處理感知衝突

### 問題

目前感知層是兩個獨立通道，沒有衝突解決機制：
- `detector.py`：確定性（pixel_diff_ratio, SSIM, console error）
- Vision LLM：語意理解（screen_id, elements, game_state）

實際會發生的矛盾場景：
- detector 說 pixel_diff = 0.02（幾乎沒變）但 Vision 說完全不同的 screen → 可能是 Vision 幻覺
- detector 說 pixel_diff = 0.8（大變）但 Vision 說同一個 screen → 可能是動態背景（魚群移動）
- OCR 讀到 score = 100 但 Vision 讀到 score = 1000 → 十倍差距，誰對？

沒有仲裁機制 → oracle 可能基於幻覺報 false positive bug。

### 建議

引入 **Feature Disagreement Score (FDS)** 模式的 sensor fusion layer，參考自動駕駛多模態融合：

```python
class SensorFusion:
    def resolve(self, detector_result, vision_result, ocr_result=None):
        # 計算跨感測器 disagreement score
        fds = self._compute_disagreement(detector_result, vision_result, ocr_result)

        if fds < LOW_THRESHOLD:
            # 高一致性 → mid-fusion（直接合併，取最高信心源）
            return self._merge_confident(detector_result, vision_result, ocr_result)
        elif fds > HIGH_THRESHOLD:
            # 高衝突 → late-fusion（各訊號獨立投票 + 仲裁規則）
            return self._arbitrate(detector_result, vision_result, ocr_result)
        else:
            # 中等衝突 → 標記 uncertainty，升級到重新截圖確認
            return self._request_reconfirmation()
```

仲裁優先順序（依確定性排序）：
1. **Console error / WebGL context lost** → 最高優先，確定性事實
2. **OCR 數字讀取**（confidence > 0.9）→ 確定性，優先於 Vision 數字
3. **pixel_diff_ratio** → 客觀像素統計（但「解釋」可能錯）
4. **Vision LLM screen_id** → 最有語意理解力，但可能幻覺
5. **Vision LLM game_state 數字** → 最不可靠（OCR 誤讀 + 幻覺雙重風險）

**效益**：
- 明確的衝突處理策略，不再「兩個訊號各做各的」
- 降低 Vision 幻覺對 oracle 結果的污染
- 動態選擇融合策略（一致時省 compute，衝突時多花時間仲裁）
- 為未來多感測器（音訊、網路封包分析）預留擴展點

### 參考資料

- CoRiM: Conflict-driven Risk Minimization for Dynamic Multimodal Fusion（CVPR 2026, 衝突量化 + Frank-Wolfe 自適應權重）：https://openaccess.thecvf.com/content/CVPR2026/papers/Zou_CoRiM_Conflict-driven_Risk_Minimization_for_Dynamic_Multimodal_Fusion_CVPR_2026_paper.pdf
- FDSNet: Dynamic Multimodal Fusion via Feature Disagreement Scoring（Nature Scientific Reports 2025, 自動駕駛 Camera+LiDAR+Radar fusion, +3% NDS improvement）：https://doi.org/10.1038/s41598-025-25693-y

### 優先級：中高（感知可靠性保障，建議 1 的 OCR 層完成後整合）

---

## 整體優先順序

| 優先 | 建議 | 解決的 AD | 理由 |
|------|------|-----------|------|
| P0 | 建議 4（SQLite 後端） | AD-5, AD-6, AD-8 | 資料基礎設施，所有 ML 功能的前置條件 |
| P0 | 建議 2（DINOv2 embedding） | AD-5 | screen_id 穩定化，是建議 3/5 的前置條件 |
| P1 | 建議 1（本地 OCR） | AD-2, AD-9 | 降低成本/延遲，提供確定性數值基準 |
| P1 | 建議 5（Sensor Fusion） | AD-4 | 感知可靠性保障，防止 false positive |
| P2 | 建議 3（Q-Learning 探索） | AD-6, AD-8 | 需 screen_id 穩定後才有意義 |

---

## 與現有 AD 的對應關係

- **AD-2**（oracle）→ 建議 1 補充確定性 OCR 層，建議 5 加入仲裁機制
- **AD-4**（座標 grounding）→ 建議 5 的 sensor fusion 為點擊後斷言提供多訊號仲裁
- **AD-5**（screen_id 穩定化）→ 建議 2 直接解決，用 learned embedding 取代手工特徵
- **AD-6**（confidence 升降）→ 建議 4 提供結構化後端支撐 counter + timestamp
- **AD-8**（覆蓋率）→ 建議 3 的 curiosity reward 天然定義覆蓋率指標
- **AD-9**（感知分層與成本）→ 建議 1 + 2 完善 L1/L1.5/L2 三層感知成本梯度

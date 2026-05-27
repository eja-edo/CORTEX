# CORTEX — Kế Hoạch Đồ Án Tốt Nghiệp
### AI-Integrated Productivity Platform: Từ Chatbot Đến Agentic Workspace

---

## 1. PHÂN TÍCH THỊ TRƯỜNG & KHOẢNG TRỐNG CẦN LẤP

### 1.1 Bối cảnh 2026

Theo nghiên cứu thị trường hiện tại:

- **Gartner (2026):** Lộ trình AI đang ở giai đoạn *task-specific agents*, chuẩn bị tiến lên *collaborative agents* (2027). Cortex nằm đúng ở điểm giao này — cơ hội lý tưởng cho đồ án.
- **Deloitte 2026:** Chỉ 11% tổ chức đang dùng agentic AI trong production thực tế; 38% vẫn đang pilot. Khoảng trống này chính là lý do Cortex có giá trị nghiên cứu.
- **Stack Overflow 2025:** 61% developer coi "tìm lại thông tin đã gặp" là điểm đau hàng đầu mỗi ngày.

### 1.2 Đối thủ và khoảng trống

| Công cụ | Điểm mạnh | Thiếu gì |
|---|---|---|
| **Notion AI** | Collaborative workspace, database mạnh | AI chỉ tạo text, không thực thi hành động thực sự |
| **Obsidian** | Local-first, privacy, graph view | Không có AI agent, không xử lý media (video/audio) |
| **Mem.ai** | AI-native từ đầu, tự tổ chức | Không có STT/OCR, không agentic tool calling |
| **Microsoft Copilot** | Tích hợp sâu M365 | Bị lock vào hệ sinh thái Microsoft |

**→ Khoảng trống Cortex lấp được:** Nền tảng duy nhất kết hợp (1) xử lý media đa phương thức, (2) AI agent có thể thực thi hành động thực trên dữ liệu, (3) semantic search với vector, và (4) streaming real-time — trong một hệ thống mã nguồn mở có thể nghiên cứu được.

### 1.3 Định vị học thuật

**Đề xuất tên đồ án:**
> *"Cortex: Thiết kế và Xây dựng Hệ thống Productivity Tích hợp AI Đa Phương Thức với Kiến trúc Agentic Tool-Calling"*

**Đóng góp học thuật cốt lõi (bắt buộc phải có trong báo cáo):**
1. So sánh thực nghiệm: Single-agent vs. Multi-agent trong môi trường productivity cá nhân
2. Đánh giá hiệu quả semantic search (pgvector cosine similarity) vs. full-text search trong retrieval note thực tế
3. Đo lường latency và chất lượng của pipeline: Audio → STT → Note → Agent query

---

## 2. CÁC TÍNH NĂNG CẦN PHÁT TRIỂN THÊM

> **Nguyên tắc chọn lọc:** Mỗi tính năng phải vừa có giá trị thực tiễn cho người dùng, vừa có giá trị nghiên cứu có thể đo lường được.

---

### TÍNH NĂNG 1 — AI Meeting Assistant ⭐⭐⭐ (Ưu tiên cao nhất)

**Mô tả:**
Người dùng upload recording cuộc họp (video/audio) → hệ thống tự động: phiên âm (STT Whisper), tóm tắt nội dung, trích xuất action items, tạo các task/schedule tương ứng trong workspace.

**Luồng hoạt động chi tiết:**
```
Upload file meeting
    → STT Service (Whisper) phiên âm toàn bộ
    → Agent phân tích transcript:
        - Ai nói gì (speaker diarization nếu có)
        - Các quyết định đã đưa ra
        - Action items (ai làm gì, deadline khi nào)
    → Tự động gọi tool create_schedule() cho mỗi deadline
    → Tự động gọi tool create_note() tạo meeting summary
    → Người dùng review và approve trước khi lưu
```

**Điểm đặc sắc:**
- Vòng lặp "human-in-the-loop": AI tạo đề xuất, người dùng phê duyệt — không tự động làm hết
- Liên kết meeting note ↔ schedule ↔ người tham dự
- Có thể query sau: "Tuần trước họp về gì? Ai chịu trách nhiệm task X?"

**Giá trị nghiên cứu:** Đo pipeline latency end-to-end; so sánh chất lượng tóm tắt Gemini Flash vs Gemma

---

### TÍNH NĂNG 2 — Knowledge Graph Visualization ⭐⭐⭐

**Mô tả:**
Hiển thị toàn bộ notes/knowledge của người dùng dưới dạng đồ thị ngữ nghĩa tương tác. Các note gần nhau về ngữ nghĩa (cosine similarity cao) sẽ được nối với nhau. Người dùng có thể navigate, click vào node để đọc, và hỏi AI về cluster bất kỳ.

**Luồng hoạt động chi tiết:**
```
Backend:
    - Tính cosine similarity giữa tất cả embedding notes
    - Tạo edge khi similarity > threshold (0.75)
    - API trả về adjacency list với coordinates

Frontend (D3.js / Force-directed graph):
    - Render graph với node = note, edge = semantic link
    - Color coding theo topic cluster (K-means trên embeddings)
    - Zoom, pan, click-to-read
    - "Ask AI about this cluster" → gửi context cluster vào agent
```

**Điểm đặc sắc:**
- Khám phá kết nối ẩn mà người dùng không biết là tồn tại
- Phát hiện "knowledge gap": vùng trong graph không có note
- So sánh trực quan với Obsidian Graph View — nhưng semantic thay vì chỉ dựa trên link thủ công

**Giá trị nghiên cứu:** Đánh giá chất lượng clustering embedding; user study về khả năng khám phá thông tin

---

### TÍNH NĂNG 3 — Proactive AI Nudges ⭐⭐

**Mô tả:**
AI chủ động gợi ý hành động dựa trên context hiện tại — không đợi người dùng hỏi. Ví dụ: nhận thấy có meeting sắp diễn ra và note liên quan chưa xem → nhắc; phát hiện task quá hạn → cảnh báo; thấy note cũ liên quan đến việc đang làm → gợi ý đọc lại.

**Luồng hoạt động chi tiết:**
```
Background scheduler (chạy mỗi N phút):
    - Lấy context hiện tại: upcoming schedules (15-30 phút tới)
    - Query semantic search: notes liên quan đến event sắp tới
    - Kiểm tra overdue tasks
    - Rule engine + LLM scoring để xếp hạng độ ưu tiên nudge
    - Push notification (WebSocket / SSE) kèm giải thích ngắn gọn

Người dùng có thể:
    - Snooze nudge
    - "Don't show this type again"
    - Mở trực tiếp item liên quan
```

**Điểm đặc sắc:**
- Giải thích tại sao AI gợi ý (explainability)
- Học từ hành vi người dùng: nudge bị ignore nhiều → giảm tần suất
- Phân biệt urgent vs. informational nudge

**Giá trị nghiên cứu:** Đánh giá precision/recall của nudge; user study về mức độ hữu ích vs. phiền nhiễu

---

### TÍNH NĂNG 4 — Document Q&A với RAG Pipeline ⭐⭐

**Mô tả:**
Người dùng upload tài liệu (PDF, DOCX, TXT) → chunking → embedding → lưu vào vector store → có thể hỏi đáp tự nhiên về nội dung tài liệu bất kỳ lúc nào.

**Luồng hoạt động chi tiết:**
```
Upload:
    - Parse document (PDFplumber / python-docx)
    - Chunking: 512 token chunks với 50 token overlap
    - Embed mỗi chunk (Gemini text-embedding-004)
    - Lưu vào PostgreSQL pgvector kèm metadata (doc_id, page, chunk_index)

Query:
    - User hỏi qua chat agent
    - Agent gọi tool search_document(query, doc_id?)
    - Retrieve top-K chunks (cosine similarity)
    - Reranking: cross-encoder hoặc LLM-as-judge
    - Agent trả lời có trích dẫn (trang, đoạn)
```

**Điểm đặc sắc:**
- Cite nguồn cụ thể: "Theo trang 12, đoạn 3..."
- Multi-document query: hỏi trên nhiều tài liệu cùng lúc
- Persistent: upload một lần, hỏi mãi mãi

**Giá trị nghiên cứu:** So sánh chunking strategies; đánh giá retrieval quality (MRR, NDCG); so sánh với BM25 baseline

---

### TÍNH NĂNG 5 — Smart Capture & Quick Add ⭐⭐

**Mô tả:**
Nút capture nhanh ở bất kỳ trang nào: người dùng paste URL / text / ảnh → AI tự động phân loại (note? task? event?), trích xuất thông tin chính, và đặt vào đúng chỗ trong workspace.

**Luồng hoạt động chi tiết:**
```
Input: text paste, URL, image screenshot
    
    URL → fetch nội dung trang → AI tóm tắt → tạo note
    Text thuần → AI classify: {note | task | event | contact}
    Image → OCR → text → tương tự text thuần
    
Agent quyết định:
    - Đây là task → tạo schedule với deadline ước tính
    - Đây là kiến thức → tạo note, gán tags tự động
    - Đây là meeting info → tạo calendar event
    
User xác nhận trong 3 giây trước khi lưu (có thể undo)
```

**Điểm đặc sắc:**
- Friction-free: capture xong là quên, AI lo phần còn lại
- Undo trong 10 giây (không mất dữ liệu)
- Hoạt động offline, sync khi có mạng

---

### TÍNH NĂNG 6 — AI Evaluation Dashboard ⭐⭐ (Quan trọng cho báo cáo)

**Mô tả:**
Dashboard nội bộ hiển thị các metrics chất lượng AI: tool calling accuracy, retrieval precision, response latency, model comparison. Đây là tính năng phục vụ nghiên cứu và báo cáo đồ án là chính.

**Metrics cần track:**
```
Tool Calling:
    - Tool call accuracy (đúng tool, đúng args)
    - Số lần loop trung bình per conversation
    - Tool execution latency (ms)

Retrieval (Semantic Search):
    - Precision@K (K=3,5,10)
    - Mean Reciprocal Rank (MRR)
    - So sánh với BM25 full-text baseline

Response Quality:
    - Latency TTFT (Time to First Token)
    - Total latency P50/P95/P99
    - User thumbs up/down rate

Model Comparison:
    - Gemini Flash vs Gemma: quality vs cost tradeoff
    - Round-robin distribution effectiveness
```

**Giá trị đồ án:** Đây là phần tạo ra số liệu thực nghiệm cho chương 4-5 của báo cáo

---

## 3. ROADMAP THỰC HIỆN 4 THÁNG

### Tháng 1 — Consolidate & Foundation (4 tuần)

**Tuần 1-2: Refactor & Clean Architecture**
- [ ] Viết unit tests cho AgentService, ToolRegistry (target: >70% coverage)
- [ ] Document API với OpenAPI/Swagger đầy đủ
- [ ] Setup CI/CD pipeline (GitHub Actions)
- [ ] Chuẩn bị dataset thử nghiệm: 50 notes thực, 20 conversation logs

**Tuần 3-4: Tính năng Smart Capture + Evaluation Framework**
- [ ] Implement Smart Capture endpoint (URL, text, image)
- [ ] Setup AI Evaluation Dashboard (metrics collection + basic UI)
- [ ] Baseline benchmark: đo performance hệ thống hiện tại
- [ ] Viết chương 1-2 báo cáo (giới thiệu + kiến trúc hiện tại)

**Deliverable tháng 1:** Hệ thống ổn định + số liệu baseline + 2 chương báo cáo

---

### Tháng 2 — Core Features Sprint (4 tuần)

**Tuần 5-6: AI Meeting Assistant**
- [ ] Tích hợp speaker diarization (pyannote.audio hoặc WhisperX)
- [ ] Pipeline: upload → STT → agent phân tích → tạo note/schedule draft
- [ ] UI: Meeting review screen (approve/reject từng action item)
- [ ] Test với 10 recording thực tế

**Tuần 7-8: Document Q&A (RAG Pipeline)**
- [ ] Implement document chunking service (PDFplumber + python-docx)
- [ ] Tool `search_document` với pgvector
- [ ] Reranking với Gemini Flash
- [ ] UI: Document library + chat interface
- [ ] Benchmark retrieval: đo Precision@5, MRR

**Deliverable tháng 2:** 2 tính năng hoàn chỉnh + số liệu benchmark Retrieval

---

### Tháng 3 — Differentiation Sprint (4 tuần)

**Tuần 9-10: Knowledge Graph Visualization**
- [ ] Backend: tính similarity matrix, build graph API
- [ ] Frontend: D3.js force-directed graph
- [ ] Cluster detection (K-means trên embeddings)
- [ ] "Ask AI about cluster" integration
- [ ] User test với 5 người dùng thực

**Tuần 11-12: Proactive AI Nudges**
- [ ] Background scheduler service
- [ ] Rule engine + LLM scoring cho nudge priority
- [ ] WebSocket push notification
- [ ] Feedback loop: track ignore/snooze/click
- [ ] A/B test: nudge vs. no-nudge productivity

**Deliverable tháng 3:** 2 tính năng "wow" + user study sơ bộ (N≥10)

---

### Tháng 4 — Polish, Evaluate & Write (4 tuần)

**Tuần 13-14: Experiment & Measurement**
- [ ] Chạy đầy đủ experiments: semantic search vs BM25, single vs multi-turn agent
- [ ] User study chính thức (N≥20): usability questionnaire (SUS score)
- [ ] Performance profiling: tối ưu bottlenecks
- [ ] Fix bugs từ user study

**Tuần 15-16: Báo cáo & Demo**
- [ ] Hoàn thiện toàn bộ báo cáo (chương 3-5: thiết kế, implement, đánh giá)
- [ ] Chuẩn bị demo video (5 phút, cover 3 tính năng chính)
- [ ] Slide thuyết trình (20 slides)
- [ ] Rehearsal với mentor

**Deliverable tháng 4:** Báo cáo hoàn chỉnh + demo + slides

---

## 4. CẤU TRÚC BÁO CÁO ĐỀ XUẤT

```
Chương 1: Giới thiệu (10 trang)
    1.1 Bối cảnh và động lực
    1.2 Mục tiêu nghiên cứu
    1.3 Phạm vi và đóng góp
    1.4 Cấu trúc báo cáo

Chương 2: Cơ sở lý thuyết & Công nghệ liên quan (20 trang)
    2.1 AI Agent và Tool Calling (ReAct, function calling)
    2.2 Retrieval-Augmented Generation (RAG)
    2.3 Vector Embeddings và Semantic Search
    2.4 Multi-modal AI (STT, OCR)
    2.5 Khảo sát các hệ thống liên quan (Notion, Obsidian, Mem.ai)

Chương 3: Thiết kế Hệ thống (25 trang)
    3.1 Kiến trúc tổng thể (microservices)
    3.2 Agent Service: thiết kế tool calling loop
    3.3 Knowledge Layer: embedding, indexing, retrieval
    3.4 Media Processing: OCR + STT pipeline
    3.5 Tính năng mới: Meeting Assistant, Knowledge Graph, RAG
    3.6 Thiết kế UX

Chương 4: Hiện thực (20 trang)
    4.1 Công nghệ và môi trường
    4.2 Các thách thức và giải pháp kỹ thuật
    4.3 Chi tiết implement từng module

Chương 5: Thực nghiệm và Đánh giá (25 trang)
    5.1 Thiết kế thực nghiệm
    5.2 Đánh giá Retrieval (Precision@K, MRR, so sánh BM25)
    5.3 Đánh giá Agent (tool accuracy, conversation quality)
    5.4 Đánh giá Pipeline (latency, throughput)
    5.5 User Study: SUS Score, task completion rate
    5.6 Phân tích kết quả và thảo luận

Chương 6: Kết luận (5 trang)
    6.1 Tóm tắt đóng góp
    6.2 Hạn chế
    6.3 Hướng phát triển tương lai
```

---

## 5. ĐÁNH GIÁ ĐỘ NỔI BẬT

### So sánh với các đồ án thông thường

| Tiêu chí | Đồ án thường | Cortex (mục tiêu) |
|---|---|---|
| Scope | CRUD app + AI chatbot | AI-integrated platform, 3 microservices |
| Tính thực tiễn | Demo được | Có thể dùng thực tế hàng ngày |
| Số liệu | Minimal | Benchmark đầy đủ: Precision@K, latency, SUS |
| Sự phức tạp | 1 AI feature | 10+ AI tools, multi-modal, streaming |
| Khả năng mở rộng | Hardcoded | ToolRegistry extensible, có thể add tool mới |

### Điểm yếu cần chú ý (để không bị hỏi khó)

1. **Không so sánh đủ baseline:** Phải có experiment so sánh semantic search vs. full-text search với số liệu cụ thể
2. **User study quá ít:** Cần tối thiểu 15-20 người, không phải chỉ bạn bè
3. **Không có novelty rõ ràng:** Cần định nghĩa rõ "đóng góp mới" — đề xuất: kiến trúc kết hợp multi-modal + agentic trong personal productivity, được đánh giá thực nghiệm
4. **Phụ thuộc Gemini API:** Cần có plan B nếu API thay đổi pricing; thêm Ollama local model làm fallback

### Điều làm Cortex thực sự nổi bật

- **Duy nhất** kết hợp cả OCR + STT + semantic search + tool-calling agent trong 1 hệ thống open
- **Không chỉ là chatbot:** AI có thể thực sự tạo, sửa, xóa dữ liệu người dùng
- **Multimodal từ đầu:** Xử lý text + video + audio + image trong cùng workflow
- **Streaming real-time:** SSE cho feedback tức thì, không phải chờ đợi
- **Có thể tự deploy:** Không lock-in vendor, tất cả infrastructure là open source

---

## 6. TECH DEBT CẦN XỬ LÝ TRƯỚC KHI ADD TÍNH NĂNG MỚI

Ưu tiên làm trước khi code thêm tính năng:

1. **Unit tests:** AgentService và ToolRegistry hiện chưa có test — đây là risk lớn khi refactor
2. **Rate limit handling:** Gemini round-robin tốt, nhưng cần circuit breaker pattern khi tất cả models đều down
3. **Error boundary:** Conversation không được corrupt khi tool execution fail giữa chừng
4. **Embedding job queue:** Hiện tại embed đồng bộ — cần async queue để không block request
5. **Pagination:** API `/notes` và `/conversations` cần cursor-based pagination khi data lớn
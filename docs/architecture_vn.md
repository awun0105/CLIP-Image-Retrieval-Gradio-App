Đây là kiến trúc tổng thể của app này:

**1. Một service Python duy nhất**
App chạy như một process Python qua `uvicorn`. Entry point là [src/server.py](/home/lqaq/PROJECT/CLIP-Image-Retrieval-Gradio-App/src/server.py). File này làm 3 việc chính:

1. Tạo FastAPI app.
2. Tạo Gradio UI.
3. Mount Gradio vào FastAPI tại `/ui`.

Nghĩa là API và UI cùng chạy trên một server, thường là `localhost:8000`.

**2. Lớp API**
FastAPI được tạo trong [src/api/app.py](/home/lqaq/PROJECT/CLIP-Image-Retrieval-Gradio-App/src/api/app.py).

Các route chính:

- `GET /health`: kiểm tra tình trạng app, model, Qdrant, MinIO.
- `POST /api/v1/search/text`: tìm ảnh bằng text.
- `POST /api/v1/search/image`: tìm ảnh tương tự bằng ảnh upload.
- `POST /api/v1/index/`: index một thư mục ảnh vào hệ thống.

API chỉ nhận request, validate dữ liệu, rồi gọi service layer xử lý.

**3. Lớp service / business logic**
Code chính nằm trong `src/core/`.

Các service quan trọng:

- `EmbeddingService`: load model CLIP và biến text/image thành vector 512 chiều.
- `SearchService`: nhận query, gọi CLIP tạo embedding, rồi query Qdrant.
- `IndexingService`: đọc ảnh từ thư mục, tạo embedding, upload ảnh lên MinIO, lưu vector vào Qdrant.
- `ImageService`: lấy presigned URL từ MinIO để frontend/API có thể hiển thị ảnh.

Model CLIP được lazy load, tức là chỉ load khi có request cần embedding, không load ngay khi app startup.

**4. Lớp lưu trữ**
App dùng 2 hệ thống storage ngoài:

- **Qdrant**: vector database để lưu embedding của ảnh và tìm kiếm similarity bằng cosine distance.
- **MinIO**: object storage kiểu S3 để lưu file ảnh thật.

Tách như vậy là đúng kiến trúc retrieval: Qdrant lưu “vector để tìm kiếm”, MinIO lưu “ảnh để hiển thị”.

**5. Luồng tìm kiếm bằng text**
Ví dụ user nhập: `"red floral dress"`.

Luồng xử lý:

```text
Browser / API client
 -> FastAPI route /api/v1/search/text
 -> SearchService
 -> EmbeddingService tạo text embedding bằng CLIP
 -> VectorStore query Qdrant
 -> ImageService lấy URL ảnh từ MinIO
 -> trả kết quả về UI/API
```

Kết quả gồm score, caption/meta, object key và URL ảnh.

**6. Luồng tìm kiếm bằng ảnh**
User upload một ảnh mẫu.

```text
Browser
 -> FastAPI route /api/v1/search/image
 -> PIL đọc ảnh
 -> EmbeddingService tạo image embedding
 -> Qdrant tìm vector gần nhất
 -> MinIO trả URL ảnh kết quả
 -> response
```

Text search và image search dùng cùng một embedding space của CLIP, nên cả text và ảnh đều có thể so sánh với ảnh đã index.

**7. Luồng index ảnh**
Khi gọi `/api/v1/index/`, app sẽ:

```text
Đọc folder ảnh
 -> encode từng ảnh bằng CLIP
 -> upload ảnh lên MinIO
 -> lưu vector + metadata vào Qdrant
```

Sau đó ảnh mới có thể được tìm kiếm.

**8. Dependency Injection**
[src/api/dependencies.py](/home/lqaq/PROJECT/CLIP-Image-Retrieval-Gradio-App/src/api/dependencies.py) dùng `@lru_cache(maxsize=1)` để tạo singleton cho settings, model service, Qdrant store, MinIO store, search/index services.

Điều này giúp app không tạo lại model hoặc client storage mỗi request.

**9. UI Gradio**
UI nằm trong `src/ui/gradio_app.py`. Nó không xử lý logic riêng nhiều, mà gọi lại `SearchService` và `ImageService`. Vì vậy REST API và Gradio UI dùng chung business logic.

**10. Docker deployment**
`docker-compose.yml` chạy 3 service:

```text
app     -> FastAPI + Gradio + CLIP
qdrant  -> vector database
minio   -> object storage
```

App nói chuyện với Qdrant qua `http://qdrant:6333`, và MinIO qua `minio:9000` trong Docker network.

Tóm lại: đây là một monolithic Python service có FastAPI + Gradio ở lớp presentation, `core/` làm business logic, Qdrant lưu vector, MinIO lưu ảnh, và CLIP là model trung tâm để biến text/image thành embedding.

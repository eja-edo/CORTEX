# OCR Service - Phase 1

Standalone OCR microservice for video processing.

## Status

Phase 1: Independent service, consumes from Redis stream, processes videos, writes to MongoDB, enqueues LLM tasks.

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Copy and configure environment
cp .env.example .env
# Edit .env with your settings

# Run validation
python validate_phase1.py

# Start service (FastAPI with uvicorn)
python main.py

# Or run with uvicorn directly
uvicorn main:app --host 0.0.0.0 --port 8001 --reload
```

### Health Checks

Once running, the service exposes health endpoints:

```bash
# Health check
curl http://localhost:8001/health

# Readiness check (verifies consumer is running)
curl http://localhost:8001/ready

# API documentation (automatic)
http://localhost:8001/docs
```

## Architecture

```
Redis Stream (ocr:processor:stream)
    ↓
OCR Consumer (consumer group: ocr-external-workers)
    ↓
Task Processor
    ├── Download from MinIO
    ├── Run OCR pipeline
    ├── Process layout
    └── Save to MongoDB
    ↓
Wait for transcript (timeout: 300s)
    ↓
Enqueue LLM task (llm:processor:stream)
```

## Configuration

All configuration via environment variables. See `.env.example` for details.

### Key Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection URL |
| `OCR_CONSUMER_GROUP` | `ocr-external-workers` | Consumer group name |
| `MINIO_ENDPOINT` | `localhost:9000` | MinIO/S3 endpoint |
| `MONGODB_URL` | `mongodb://localhost:27017` | MongoDB connection URL |
| `TRANSCRIPT_WAIT_TIMEOUT_SECONDS` | `300` | Max wait time for transcript |
| `OCR_TEMP_DIR` | `/tmp/ocr_processing` | Temp directory for downloads |

## Key Differences from Embedded Worker

1. **No PostgreSQL coupling** - OCR service only writes to MongoDB
2. **No status callback** - Internal API endpoint is for LLM service (future phase)
3. **Simplified MongoDB client** - Removed event loop workaround (not needed in single-process service)
4. **Own consumer group** - `ocr-external-workers` vs embedded's `ocr-processor-workers`

## Project Structure

```
ocr_service/
├── config.py                    # Pydantic settings
├── main.py                      # FastAPI entry point
├── requirements.txt             # Python dependencies
├── .env.example                 # Environment template
├── validate_phase1.py           # Validation script
│
├── pipeline/                    # OCR pipeline (copied from backend)
│   ├── __init__.py
│   ├── video_pipeline.py       # run_pipeline()
│   └── layout_processor.py     # process_metadata_file()
│
├── storage/                     # External service clients
│   ├── __init__.py
│   ├── minio_client.py         # MinIO download
│   └── mongo_client.py         # MongoDB OCR writer
│
└── worker/                      # Consumer & processor
    ├── __init__.py
    ├── consumer.py              # Redis stream consumer
    ├── processor.py             # Task processor
    └── transcript_waiter.py     # Transcript polling
```

## Validation Checklist

Before considering Phase 1 complete, verify:

- [ ] Service starts without crash
- [ ] EasyOCR model loads successfully
- [ ] Redis connection established
- [ ] MongoDB connection established
- [ ] MinIO connection established
- [ ] Consumer group created in Redis
- [ ] Test task consumed and processed
- [ ] OCR frames written to MongoDB
- [ ] LLM task enqueued to Redis stream
- [ ] Temp files cleaned up after processing
- [ ] No OOM kill after processing real video
- [ ] Logs contain sufficient debug information

## Running Validation

```bash
python validate_phase1.py
```

Expected output:
```
============================================================
Phase 1 Validation Checklist
============================================================
[PASS] Redis connection: OK
[PASS] Consumer group 'ocr-external-workers': OK
[PASS] MongoDB connection: OK
[PASS] MinIO connection: OK
[PASS] Pipeline imports: OK
[PASS] Storage imports: OK

Result: 6/6 checks passed
============================================================
```

## Next Steps (Phase 2)

- Deploy OCR service alongside backend
- Run both consumer groups in parallel (dual-run)
- Compare output between embedded and external modes
- Monitor for 48 hours

## Troubleshooting

### Service won't start
- Check `.env` file exists and has correct values
- Verify Redis, MongoDB, and MinIO are running
- Run `python validate_phase1.py` to check connections
- Check port 8001 is not already in use

### Consumer not receiving tasks
- Verify consumer group name matches: `OCR_CONSUMER_GROUP=ocr-external-workers`
- Check Redis stream has messages: `redis-cli XLEN ocr:processor:stream`
- Ensure backend is enqueueing tasks to correct stream
- Check `/ready` endpoint to verify consumer is running

### MongoDB connection fails
- Verify `MONGODB_URL` is correct
- Check MongoDB is accessible from service network
- Ensure database name matches: `MONGODB_DB_NAME=cortex`

### Health check fails
- Service running but `/health` returns error: Check logs for startup errors
- `/ready` returns "not ready": Consumer failed to start, check logs for Redis connection errors

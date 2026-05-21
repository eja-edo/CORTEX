import os
import logging
from pathlib import Path
from fastapi import FastAPI
from contextlib import asynccontextmanager
from dotenv import load_dotenv

# Load environment variables from .env file
_env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=_env_path)

from service.redis.redis_transcription_queue_service import RedisTranscriptionQueueService
from service.whisper_transcription_processor import transcribe_task, WhisperTranscriptionProcessor
from utils.logger import get_logger
from fastapi import FastAPI


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup → Shutdown lifecycle."""
    
    # Initialize Whisper transcription if enabled
    transcription_queue = RedisTranscriptionQueueService()
    transcription_queue.set_processor(transcribe_task)  # Set Whisper processor
    await transcription_queue.start()
        
    # Pre-initialize Whisper model (optional, can be lazy loaded)
    whisper_processor = WhisperTranscriptionProcessor()
    await whisper_processor.initialize()
    
    
    yield
    
    # Shutdown
    if transcription_queue is not None:
        await transcription_queue.stop()
    if whisper_processor is not None:
        await whisper_processor.shutdown()


# Init logging and FastAPI
# Get log level from environment variable
log_level_str = os.getenv('LOG_LEVEL', 'INFO').upper()
log_level = getattr(logging, log_level_str, logging.INFO)
logger = get_logger(__name__)

app = FastAPI(lifespan=lifespan)


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "main:app",
        host="localhost",
        port=8008,
        log_level=log_level_str.lower(),
    )

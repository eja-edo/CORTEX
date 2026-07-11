#!/usr/bin/env python
"""
Run the Cortex Scheduling API server
"""

import uvicorn
from app.utils.logger import _configure_root_logger

if __name__ == "__main__":
    # Configure logging early to suppress SQLAlchemy before app initialization
    _configure_root_logger()
    
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        timeout_graceful_shutdown=30,
        log_config=None  # Use our custom logging config, don't override with uvicorn's
    )

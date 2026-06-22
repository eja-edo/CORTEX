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
        host="::",
        port=8000,
        reload=False,
        log_config=None  # Use our custom logging config, don't override with uvicorn's
    )

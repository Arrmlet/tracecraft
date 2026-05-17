"""
FastAPI server for tracecraft.

Coordination layer for multi-agent AI systems.
"""

import os
from datetime import datetime
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

from tracecraft_server.core.config import ConfigManager
from tracecraft_server.storage.seaweed import SeaweedClient
from tracecraft_server.storage.buckets import BucketManager
from tracecraft_server.core.security import AuthManager, TokenManager


# Pydantic models for API responses
class HealthResponse(BaseModel):
    """Health check response"""
    status: str
    timestamp: str

class StatusResponse(BaseModel):
    """Status response"""
    status: str
    version: str

class TokenRequest(BaseModel):
    """API token request"""
    api_key: str

class S3Credentials(BaseModel):
    """S3 credentials"""
    endpoint_url: str
    access_key: str
    secret_key: str
    bucket_name: str
    region: str


def create_app(config_path: Optional[str] = None) -> FastAPI:
    """
    Create FastAPI application.

    Args:
        config_path: Path to configuration file

    Returns:
        FastAPI application instance
    """
    app = FastAPI(
        title="Tracecraft API",
        description="Coordination layer for multi-agent AI systems",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc"
    )

    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Health check endpoint
    @app.get("/health", response_model=HealthResponse, tags=["System"])
    async def health_check():
        """Check if the API is running"""
        return HealthResponse(
            status="healthy",
            timestamp=datetime.now().isoformat()
        )

    # Status endpoint
    @app.get("/api/v1/status", response_model=StatusResponse, tags=["System"])
    async def status():
        """Get API status"""
        return StatusResponse(
            status="ok",
            version="0.1.0"
        )

    return app


def main(config=None):
    """Main entry point for FastAPI server"""
    # Handle both CLI call with config and direct call
    if config is None:
        # Called directly, parse command line arguments
        import argparse

        parser = argparse.ArgumentParser(description='Tracecraft Server')
        parser.add_argument('--host', default='127.0.0.1', help='Host to bind to')
        parser.add_argument('--port', type=int, default=8000, help='Port to bind to')
        parser.add_argument('--config', help='Path to config file')
        parser.add_argument('--reload', action='store_true', help='Enable auto-reload')

        args = parser.parse_args()

        app = create_app(args.config)
        host = args.host
        port = args.port
        reload = args.reload
    else:
        # Called from CLI with config object
        app = create_app()
        host = getattr(config.ui, 'host', '127.0.0.1')
        port = getattr(config.ui, 'port', 8000)
        reload = getattr(config.ui, 'debug', False)

    print(f"Starting Tracecraft server...")
    print(f"Server: http://{host}:{port}")
    print(f"API Docs: http://{host}:{port}/docs")

    uvicorn.run(
        app,
        host=host,
        port=port,
        reload=reload
    )


if __name__ == "__main__":
    main()

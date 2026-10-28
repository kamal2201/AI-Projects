from __future__ import annotations

import logging
from typing import Optional
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class MediaAsset(BaseModel):
    """Verified media asset."""
    url: str = Field(..., description="Secure HTTPS asset URL")
    alt: str = Field(..., description="Accessible description")
    caption: Optional[str] = Field(None, description="Optional caption")


class ImageProvider:
    """Interface for verified image generation or retrieval."""

    async def resolve_image(self, query: str) -> Optional[MediaAsset]:
        """Resolve a verified image asset or return None if provider is not configured.
        
        Note: Dedicated generative image services (e.g. Imagen/DALL-E) are planned for Phase 4.
        """
        logger.debug("ImageProvider queried for '%s' (no external provider configured)", query)
        return None


# Global singleton instance for clean dependency injection
_image_provider: Optional[ImageProvider] = None


def get_image_provider() -> ImageProvider:
    global _image_provider
    if _image_provider is None:
        _image_provider = ImageProvider()
    return _image_provider

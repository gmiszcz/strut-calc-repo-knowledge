"""Embed text with Amazon Bedrock Titan Text Embeddings v2.

A thin boundary over the Bedrock runtime: it turns a string into a float vector
and nothing more. Credentials come from the shared AWS profile (SSO), so the
caller must have run ``aws sso login`` first. The query path and the build path
use the same embedder so a stored chunk and a search query land in the same
vector space.
"""

from __future__ import annotations

import json
import logging

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger(__name__)


class EmbeddingError(RuntimeError):
    """Raised when Bedrock cannot return an embedding."""


class BedrockEmbedder:
    """Embeds text through a single Bedrock model."""

    def __init__(self, profile: str, region: str, model_id: str, embed_dim: int) -> None:
        """Build the Bedrock runtime client.

        Args:
            profile: AWS profile name from ``~/.aws``.
            region: AWS region hosting the model.
            model_id: Bedrock embedding model id.
            embed_dim: Requested embedding dimensionality.
        """
        self._model_id = model_id
        self._embed_dim = embed_dim
        session = boto3.Session(profile_name=profile, region_name=region)
        self._client = session.client(
            "bedrock-runtime",
            config=Config(retries={"max_attempts": 5, "mode": "adaptive"}),
        )

    def embed(self, text: str) -> list[float]:
        """Return the embedding vector for one piece of text.

        Args:
            text: The text to embed.

        Returns:
            The embedding as a list of floats.

        Raises:
            EmbeddingError: When the model call fails or returns no vector.
        """
        body = json.dumps(
            {
                "inputText": text,
                "dimensions": self._embed_dim,
                "normalize": True,
            }
        )
        try:
            response = self._client.invoke_model(modelId=self._model_id, body=body)
            payload = json.loads(response["body"].read())
        except (BotoCoreError, ClientError, KeyError, json.JSONDecodeError) as exc:
            raise EmbeddingError(f"Bedrock embedding failed: {exc}") from exc

        vector = payload.get("embedding")
        if not isinstance(vector, list) or not vector:
            raise EmbeddingError("Bedrock returned no embedding vector")
        return [float(value) for value in vector]

"""Feature extraction for reaction clustering."""

from __future__ import annotations

import numpy as np
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..storage import Storage


class TextFeatureExtractor:
    """Extract text embeddings from messages using sentence-transformers."""

    def __init__(self, model_name: str = "paraphrase-multilingual-MiniLM-L12-v2"):
        """Initialize the text feature extractor.

        Args:
            model_name: Name of the sentence-transformers model to use.
                        Default is multilingual model for Japanese support.
        """
        self.model_name = model_name
        self._model = None

    @property
    def model(self):
        """Lazy load the model."""
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)
        return self._model

    @property
    def embedding_dim(self) -> int:
        """Get the embedding dimension."""
        return self.model.get_sentence_embedding_dimension()

    def embed_texts(self, texts: list[str], show_progress: bool = True) -> np.ndarray:
        """Embed a list of texts.

        Args:
            texts: List of texts to embed
            show_progress: Whether to show progress bar

        Returns:
            (N, D) array of embeddings
        """
        if not texts:
            return np.array([]).reshape(0, self.embedding_dim)
        return self.model.encode(texts, show_progress_bar=show_progress)

    def get_reaction_embeddings(
        self,
        storage: Storage,
        use_cache: bool = True,
    ) -> tuple[np.ndarray, list[str]]:
        """Get aggregated embeddings for each reaction type.

        For each unique reaction, computes the average embedding of all messages
        that received that reaction.

        Args:
            storage: Storage instance to get data from
            use_cache: Whether to use cached embeddings

        Returns:
            (embeddings, reaction_names) where embeddings is (N, D) array
        """
        reactions = storage.get_unique_reactions()
        if not reactions:
            return np.array([]).reshape(0, self.embedding_dim), []

        embeddings = []

        for reaction in reactions:
            messages = storage.get_messages_for_reaction(reaction)
            if not messages:
                # Use zero vector for reactions with no messages
                embeddings.append(np.zeros(self.embedding_dim))
                continue

            # Check cache first
            if use_cache:
                cached_embeddings = []
                uncached_messages = []
                uncached_indices = []

                for i, msg in enumerate(messages):
                    # Use message hash as cache key
                    msg_hash = str(hash(msg))
                    cached = storage.get_embedding(msg_hash, self.model_name)
                    if cached is not None:
                        cached_embeddings.append(np.frombuffer(cached, dtype=np.float32))
                    else:
                        uncached_messages.append(msg)
                        uncached_indices.append(i)

                # Compute uncached embeddings
                if uncached_messages:
                    new_embeddings = self.embed_texts(uncached_messages, show_progress=False)
                    for idx, emb in zip(uncached_indices, new_embeddings):
                        msg_hash = str(hash(messages[idx]))
                        storage.save_embedding(
                            msg_hash,
                            self.model_name,
                            emb.astype(np.float32).tobytes(),
                            len(emb),
                        )
                        cached_embeddings.insert(idx, emb)

                msg_embeddings = np.array(cached_embeddings)
            else:
                msg_embeddings = self.embed_texts(messages, show_progress=False)

            # Average pooling
            avg_embedding = msg_embeddings.mean(axis=0)
            embeddings.append(avg_embedding)

        storage.commit()
        return np.array(embeddings), reactions


class BehaviorFeatureExtractor:
    """Extract user behavior patterns for reactions."""

    def build_user_preference_matrix(
        self,
        storage: Storage,
        reaction_names: list[str],
    ) -> np.ndarray:
        """Build normalized user preference vectors for each reaction.

        For each reaction, creates a vector showing which users prefer this reaction.

        Args:
            storage: Storage instance
            reaction_names: List of reaction names (determines output order)

        Returns:
            (N_reactions, N_users) array of normalized preferences
        """
        user_counts = storage.get_user_reaction_counts()
        users = sorted(user_counts.keys())

        if not users or not reaction_names:
            return np.zeros((len(reaction_names), 1))

        # Build matrix: reactions x users
        matrix = np.zeros((len(reaction_names), len(users)))

        for i, reaction in enumerate(reaction_names):
            for j, user in enumerate(users):
                count = user_counts.get(user, {}).get(reaction, 0)
                matrix[i, j] = count

        # Normalize per reaction (L2 norm)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1  # Avoid division by zero
        matrix = matrix / norms

        return matrix

    def build_cooccurrence_matrix(
        self,
        storage: Storage,
        reaction_names: list[str],
    ) -> np.ndarray:
        """Build reaction co-occurrence feature vectors.

        For each reaction, creates a vector showing which other reactions
        tend to appear on the same messages.

        Args:
            storage: Storage instance
            reaction_names: List of reaction names (determines output order)

        Returns:
            (N_reactions, N_reactions) array of normalized co-occurrences
        """
        cooccurrence = storage.get_reaction_cooccurrence()

        n = len(reaction_names)
        if n == 0:
            return np.zeros((0, 0))

        matrix = np.zeros((n, n))
        name_to_idx = {name: i for i, name in enumerate(reaction_names)}

        for r1, related in cooccurrence.items():
            if r1 not in name_to_idx:
                continue
            i = name_to_idx[r1]
            for r2, count in related.items():
                if r2 not in name_to_idx:
                    continue
                j = name_to_idx[r2]
                matrix[i, j] = count
                matrix[j, i] = count

        # Normalize per reaction (L2 norm)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1
        matrix = matrix / norms

        return matrix

    def get_behavior_features(
        self,
        storage: Storage,
        reaction_names: list[str],
    ) -> np.ndarray:
        """Get combined behavior features for reactions.

        Combines user preference and co-occurrence features.

        Args:
            storage: Storage instance
            reaction_names: List of reaction names

        Returns:
            (N_reactions, D) array of behavior features
        """
        user_prefs = self.build_user_preference_matrix(storage, reaction_names)
        cooccurrence = self.build_cooccurrence_matrix(storage, reaction_names)

        # Concatenate features
        return np.hstack([user_prefs, cooccurrence])


class FeatureCombiner:
    """Combine text and behavior features with configurable weights."""

    def __init__(self, text_weight: float = 0.5, behavior_weight: float = 0.5):
        """Initialize the feature combiner.

        Args:
            text_weight: Weight for text features (0-1)
            behavior_weight: Weight for behavior features (0-1)
        """
        if text_weight < 0 or behavior_weight < 0:
            raise ValueError("Weights must be non-negative")

        # Normalize weights to sum to 1
        total = text_weight + behavior_weight
        if total == 0:
            raise ValueError("At least one weight must be positive")

        self.text_weight = text_weight / total
        self.behavior_weight = behavior_weight / total

    def combine(
        self,
        text_features: np.ndarray,
        behavior_features: np.ndarray,
    ) -> np.ndarray:
        """Combine text and behavior features.

        1. Standardize both feature sets (zero mean, unit variance)
        2. Apply weights
        3. Concatenate

        Args:
            text_features: (N, D1) array of text features
            behavior_features: (N, D2) array of behavior features

        Returns:
            (N, D1+D2) array of combined features
        """
        from sklearn.preprocessing import StandardScaler

        if text_features.shape[0] != behavior_features.shape[0]:
            raise ValueError("Feature arrays must have same number of samples")

        n_samples = text_features.shape[0]
        if n_samples == 0:
            return np.zeros((0, text_features.shape[1] + behavior_features.shape[1]))

        # Standardize
        scaler = StandardScaler()

        if text_features.shape[1] > 0:
            text_scaled = scaler.fit_transform(text_features) * self.text_weight
        else:
            text_scaled = text_features

        if behavior_features.shape[1] > 0:
            behavior_scaled = scaler.fit_transform(behavior_features) * self.behavior_weight
        else:
            behavior_scaled = behavior_features

        # Concatenate
        return np.hstack([text_scaled, behavior_scaled])

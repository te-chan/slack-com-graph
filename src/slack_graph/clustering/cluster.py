"""Clustering algorithms for reaction analysis."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field

import numpy as np
from sklearn.preprocessing import StandardScaler


@dataclass
class ClusteringResult:
    """Result of clustering analysis."""

    labels: np.ndarray
    probabilities: np.ndarray
    reaction_names: list[str]
    n_clusters: int
    silhouette_score: float | None
    algorithm: str
    params: dict = field(default_factory=dict)
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def get_cluster_members(self, cluster_id: int) -> list[tuple[str, float]]:
        """Get reaction names in a cluster with confidence scores.

        Args:
            cluster_id: The cluster ID to query

        Returns:
            List of (reaction_name, confidence) tuples, sorted by confidence descending
        """
        mask = self.labels == cluster_id
        members = []
        for i, is_member in enumerate(mask):
            if is_member:
                prob = self.probabilities[i] if self.probabilities is not None else 1.0
                members.append((self.reaction_names[i], float(prob)))
        return sorted(members, key=lambda x: -x[1])

    def get_clusters_summary(self) -> dict[int, list[str]]:
        """Get a summary of all clusters.

        Returns:
            Dict mapping cluster_id to list of reaction names
        """
        clusters: dict[int, list[str]] = {}
        for i, label in enumerate(self.labels):
            label_int = int(label)
            if label_int not in clusters:
                clusters[label_int] = []
            clusters[label_int].append(self.reaction_names[i])
        return clusters

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "run_id": self.run_id,
            "algorithm": self.algorithm,
            "params": self.params,
            "n_clusters": self.n_clusters,
            "silhouette_score": self.silhouette_score,
            "clusters": self.get_clusters_summary(),
            "assignments": [
                {
                    "reaction": name,
                    "cluster": int(label),
                    "confidence": float(self.probabilities[i])
                    if self.probabilities is not None
                    else 1.0,
                }
                for i, (name, label) in enumerate(
                    zip(self.reaction_names, self.labels)
                )
            ],
        }

    def save_to_json(self, path: str):
        """Save results to JSON file."""
        import json
        from pathlib import Path

        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)


class ReactionClusterer:
    """HDBSCAN-based reaction emoji clustering."""

    def __init__(
        self,
        min_cluster_size: int = 2,
        min_samples: int = 1,
        cluster_selection_epsilon: float = 0.0,
        metric: str = "euclidean",
    ):
        """Initialize the clusterer.

        Args:
            min_cluster_size: Minimum number of samples in a cluster
            min_samples: Number of samples in a neighborhood for core points
            cluster_selection_epsilon: Distance threshold for cluster selection
            metric: Distance metric to use
        """
        self.params = {
            "min_cluster_size": min_cluster_size,
            "min_samples": min_samples,
            "cluster_selection_epsilon": cluster_selection_epsilon,
            "metric": metric,
        }

    def fit(
        self,
        features: np.ndarray,
        reaction_names: list[str],
    ) -> ClusteringResult:
        """Cluster reactions based on combined features.

        Args:
            features: (N, D) array of features
            reaction_names: List of reaction names

        Returns:
            ClusteringResult with cluster assignments and metrics
        """
        import hdbscan
        from sklearn.metrics import silhouette_score as sklearn_silhouette

        if features.shape[0] == 0:
            return ClusteringResult(
                labels=np.array([]),
                probabilities=np.array([]),
                reaction_names=[],
                n_clusters=0,
                silhouette_score=None,
                algorithm="hdbscan",
                params=self.params,
            )

        # Standardize features
        scaler = StandardScaler()
        scaled_features = scaler.fit_transform(features)

        # Run HDBSCAN
        clusterer = hdbscan.HDBSCAN(**self.params)
        labels = clusterer.fit_predict(scaled_features)
        probabilities = clusterer.probabilities_

        # Calculate metrics
        n_clusters = len(set(labels)) - (1 if -1 in labels else 0)

        # Silhouette score requires at least 2 clusters with multiple points
        silhouette = None
        valid_mask = labels >= 0
        if valid_mask.sum() > 1 and n_clusters > 1:
            try:
                silhouette = float(
                    sklearn_silhouette(scaled_features[valid_mask], labels[valid_mask])
                )
            except ValueError:
                # Not enough clusters for silhouette score
                pass

        return ClusteringResult(
            labels=labels,
            probabilities=probabilities,
            reaction_names=reaction_names,
            n_clusters=n_clusters,
            silhouette_score=silhouette,
            algorithm="hdbscan",
            params=self.params,
        )


class KMeansClusterer:
    """K-Means based clustering as an alternative."""

    def __init__(self, n_clusters: int = 5, random_state: int = 42):
        """Initialize K-Means clusterer.

        Args:
            n_clusters: Number of clusters
            random_state: Random state for reproducibility
        """
        self.params = {
            "n_clusters": n_clusters,
            "random_state": random_state,
        }

    def fit(
        self,
        features: np.ndarray,
        reaction_names: list[str],
    ) -> ClusteringResult:
        """Cluster reactions using K-Means.

        Args:
            features: (N, D) array of features
            reaction_names: List of reaction names

        Returns:
            ClusteringResult with cluster assignments
        """
        from sklearn.cluster import KMeans
        from sklearn.metrics import silhouette_score as sklearn_silhouette

        if features.shape[0] == 0:
            return ClusteringResult(
                labels=np.array([]),
                probabilities=np.array([]),
                reaction_names=[],
                n_clusters=0,
                silhouette_score=None,
                algorithm="kmeans",
                params=self.params,
            )

        # Adjust n_clusters if we have fewer samples
        n_clusters = min(self.params["n_clusters"], len(reaction_names))
        if n_clusters < 2:
            n_clusters = 2

        # Standardize features
        scaler = StandardScaler()
        scaled_features = scaler.fit_transform(features)

        # Run K-Means
        kmeans = KMeans(
            n_clusters=n_clusters,
            random_state=self.params["random_state"],
            n_init=10,
        )
        labels = kmeans.fit_predict(scaled_features)

        # For K-Means, we don't have probabilities, use 1.0 for all
        probabilities = np.ones(len(labels))

        # Calculate silhouette score
        silhouette = None
        if n_clusters > 1:
            try:
                silhouette = float(sklearn_silhouette(scaled_features, labels))
            except ValueError:
                pass

        return ClusteringResult(
            labels=labels,
            probabilities=probabilities,
            reaction_names=reaction_names,
            n_clusters=n_clusters,
            silhouette_score=silhouette,
            algorithm="kmeans",
            params={"n_clusters": n_clusters, "random_state": self.params["random_state"]},
        )


def run_clustering(
    storage,
    text_weight: float = 0.5,
    behavior_weight: float = 0.5,
    algorithm: str = "hdbscan",
    **kwargs,
) -> ClusteringResult:
    """Run full clustering pipeline.

    Args:
        storage: Storage instance with reaction data
        text_weight: Weight for text features
        behavior_weight: Weight for behavior features
        algorithm: 'hdbscan' or 'kmeans'
        **kwargs: Additional arguments for the clusterer

    Returns:
        ClusteringResult
    """
    from .features import TextFeatureExtractor, BehaviorFeatureExtractor, FeatureCombiner

    # Build reaction contexts if needed
    if storage.count_reaction_contexts() == 0:
        storage.build_reaction_contexts()

    # Extract features
    text_extractor = TextFeatureExtractor()
    behavior_extractor = BehaviorFeatureExtractor()
    combiner = FeatureCombiner(text_weight=text_weight, behavior_weight=behavior_weight)

    text_features, reaction_names = text_extractor.get_reaction_embeddings(storage)

    if len(reaction_names) == 0:
        raise ValueError("No reactions found in database")

    behavior_features = behavior_extractor.get_behavior_features(storage, reaction_names)

    # Combine features
    combined = combiner.combine(text_features, behavior_features)

    # Cluster
    if algorithm == "hdbscan":
        clusterer = ReactionClusterer(**kwargs)
    elif algorithm == "kmeans":
        clusterer = KMeansClusterer(**kwargs)
    else:
        raise ValueError(f"Unknown algorithm: {algorithm}")

    result = clusterer.fit(combined, reaction_names)

    # Save to database
    assignments = [
        (name, int(label), float(result.probabilities[i]) if result.probabilities is not None else 1.0)
        for i, (name, label) in enumerate(zip(result.reaction_names, result.labels))
    ]

    storage.save_clustering_result(
        run_id=result.run_id,
        algorithm=result.algorithm,
        params_json=json.dumps(result.params),
        text_weight=text_weight,
        behavior_weight=behavior_weight,
        n_clusters=result.n_clusters,
        silhouette_score=result.silhouette_score,
        assignments=assignments,
    )

    return result

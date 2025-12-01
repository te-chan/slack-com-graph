import typer

from .config import load_config
from .storage import Storage
from .import_ndjson import import_ndjson
from .import_users import import_users_ndjson
from .graph import build_graph
from .export import export_graphml, export_gexf


app = typer.Typer(no_args_is_help=True)


@app.command("import-ndjson")
def import_ndjson_cmd(
    files: list[str] = typer.Argument(..., help="取り込むNDJSONファイル（複数可）"),
):
    """NDJSON（Webクライアントで記録したログ）をDBに取り込みます。"""
    cfg = load_config()
    store = Storage(cfg.db_path)
    store.init()
    counts = import_ndjson(files, store)
    typer.echo(
        f"Imported: users={counts['users']}, channels={counts['channels']}, messages={counts['messages']}, reactions={counts['reactions']} (files={counts['files']}, lines={counts['lines']}, skipped={counts['skipped']})"
    )
    typer.echo(
        f"DB totals: users={store.count_users()}, channels={store.count_channels(include_im_mpim=False)}, messages={store.count_messages()}, reactions={store.count_reactions()}"
    )


@app.command("import-users")
def import_users_cmd(
    files: list[str] = typer.Argument(..., help="取り込むUsers NDJSONファイル（users_capture.js出力）"),
):
    """Users NDJSON（users_capture.jsのdownload出力）をDBに取り込みます。"""
    cfg = load_config()
    store = Storage(cfg.db_path)
    store.init()
    counts = import_users_ndjson(files, store)
    typer.echo(
        f"Imported users: {counts['users']} (files={counts['files']}, lines={counts['lines']}, skipped={counts['skipped']})"
    )
    typer.echo(
        f"DB totals: users={store.count_users()}, channels={store.count_channels(include_im_mpim=False)}, messages={store.count_messages()}, reactions={store.count_reactions()}"
    )


@app.command()
def build(
    graphml: str = typer.Option("output/graph.graphml", help="GraphML出力先"),
    gexf: str = typer.Option("output/graph.gexf", help="GEXF出力先"),
):
    """DBからグラフを構築してGraphML/GEXFで出力します。"""
    cfg = load_config()
    store = Storage(cfg.db_path)
    G = build_graph(store)
    typer.echo(f"Graph nodes={G.number_of_nodes()}, edges={G.number_of_edges()}")
    graphml_path = export_graphml(G, path=graphml)
    gexf_path = export_gexf(G, path=gexf)
    typer.echo(f"Graph built: {graphml_path}, {gexf_path}")


# API周りのコマンドは削除しました（WebクライアントのNDJSON取り込みに一本化）


# ===== Clustering commands =====


@app.command("build-reaction-contexts")
def build_contexts_cmd(
    db_path: str = typer.Option(None, help="DBパス（指定しない場合は設定ファイルから読み込み）"),
):
    """リアクションコンテキストテーブルを構築します（リアクション→メッセージの結合）。"""
    if db_path:
        store = Storage(db_path)
    else:
        cfg = load_config()
        store = Storage(cfg.db_path)
    store.init()
    count = store.build_reaction_contexts()
    typer.echo(f"Built {count} reaction contexts")
    typer.echo(f"Unique reactions: {len(store.get_unique_reactions())}")


@app.command("cluster-reactions")
def cluster_reactions_cmd(
    db_path: str = typer.Option(None, help="DBパス（指定しない場合は設定ファイルから読み込み）"),
    text_weight: float = typer.Option(0.5, help="テキスト特徴量の重み (0-1)"),
    behavior_weight: float = typer.Option(0.5, help="行動特徴量の重み (0-1)"),
    algorithm: str = typer.Option("hdbscan", help="クラスタリングアルゴリズム (hdbscan/kmeans)"),
    min_cluster_size: int = typer.Option(2, help="最小クラスタサイズ (HDBSCAN)"),
    n_clusters: int = typer.Option(5, help="クラスタ数 (K-Means)"),
    output: str = typer.Option("output/clusters.json", help="出力JSONファイル"),
):
    """リアクション絵文字をクラスタリングします。"""
    from .clustering.cluster import run_clustering

    if db_path:
        store = Storage(db_path)
    else:
        cfg = load_config()
        store = Storage(cfg.db_path)
    store.init()

    typer.echo("Running clustering...")

    kwargs = {}
    if algorithm == "hdbscan":
        kwargs["min_cluster_size"] = min_cluster_size
    elif algorithm == "kmeans":
        kwargs["n_clusters"] = n_clusters

    result = run_clustering(
        store,
        text_weight=text_weight,
        behavior_weight=behavior_weight,
        algorithm=algorithm,
        **kwargs,
    )

    result.save_to_json(output)

    typer.echo(f"\nClustering complete!")
    typer.echo(f"  Algorithm: {result.algorithm}")
    typer.echo(f"  Clusters found: {result.n_clusters}")
    if result.silhouette_score is not None:
        typer.echo(f"  Silhouette score: {result.silhouette_score:.3f}")
    typer.echo(f"  Results saved to: {output}")

    # Show cluster summary
    typer.echo("\nCluster summary:")
    clusters = result.get_clusters_summary()
    for cluster_id in sorted(clusters.keys()):
        members = clusters[cluster_id]
        label = "Noise" if cluster_id == -1 else f"Cluster {cluster_id}"
        typer.echo(f"  {label}: {', '.join(members)}")


@app.command("show-clustering")
def show_clustering_cmd(
    db_path: str = typer.Option(None, help="DBパス（指定しない場合は設定ファイルから読み込み）"),
):
    """最新のクラスタリング結果を表示します。"""
    if db_path:
        store = Storage(db_path)
    else:
        cfg = load_config()
        store = Storage(cfg.db_path)
    store.init()

    result = store.get_latest_clustering_result()
    if not result:
        typer.echo("No clustering results found. Run 'cluster-reactions' first.")
        raise typer.Exit(1)

    typer.echo(f"Run ID: {result['run_id']}")
    typer.echo(f"Algorithm: {result['algorithm']}")
    typer.echo(f"Created: {result['created_at']}")
    typer.echo(f"Text weight: {result['text_weight']}, Behavior weight: {result['behavior_weight']}")
    typer.echo(f"Clusters: {result['n_clusters']}")
    if result['silhouette_score'] is not None:
        typer.echo(f"Silhouette score: {result['silhouette_score']:.3f}")

    typer.echo("\nAssignments:")
    # Group by cluster
    clusters: dict[int, list[str]] = {}
    for a in result['assignments']:
        cid = a['cluster']
        if cid not in clusters:
            clusters[cid] = []
        clusters[cid].append(a['reaction'])

    for cid in sorted(clusters.keys()):
        label = "Noise" if cid == -1 else f"Cluster {cid}"
        typer.echo(f"  {label}: {', '.join(clusters[cid])}")


if __name__ == "__main__":
    app()

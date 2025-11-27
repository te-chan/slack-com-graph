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


if __name__ == "__main__":
    app()

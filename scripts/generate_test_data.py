#!/usr/bin/env python3
"""
検証用のリアクションデータを生成するスクリプト

仮説検証のため、感情カテゴリごとに異なる文脈のメッセージを生成し、
各カテゴリに対応するリアクションを付与する。

使用方法:
    python scripts/generate_test_data.py [--db-path data/test_reactions.db]
"""

import argparse
import random
import sqlite3
import time
import uuid
from pathlib import Path


# 感情カテゴリと対応するリアクション・メッセージ
CATEGORIES = {
    "positive": {
        "reactions": ["+1", "thumbsup", "heart", "tada", "star", "fire", "clap", "muscle"],
        "messages": [
            "素晴らしい成果ですね！プロジェクトが成功して本当に良かったです。",
            "ありがとうございます！助かりました。",
            "完璧な実装です。これで問題が解決しました。",
            "お疲れ様でした！今回のリリースは大成功でしたね。",
            "最高のパフォーマンスでした。チーム全員の努力の結果です。",
            "素敵なアイデアですね。ぜひ採用しましょう。",
            "本番デプロイ完了しました。すべて正常に動作しています。",
            "レビューありがとうございます。修正対応しました。",
            "テスト全件パスしました！",
            "新機能のリリースおめでとうございます！",
            "すごい！こんな短期間で実装できるとは思わなかった。",
            "このアプローチ、とても良いと思います。",
            "パフォーマンスが30%改善しました。",
            "ユーザーからのフィードバックも良好です。",
            "今週のスプリント、予定通り完了しました。",
        ],
    },
    "negative": {
        "reactions": ["-1", "thumbsdown", "cry", "disappointed", "worried", "sweat"],
        "messages": [
            "残念ながら、今回のリリースは延期になりました。",
            "問題が発生しました。本番環境でエラーが出ています。",
            "申し訳ありません、バグを見つけてしまいました。",
            "テストが失敗しています。修正が必要です。",
            "この仕様では対応が難しいです。",
            "サーバーがダウンしています。緊急対応お願いします。",
            "レスポンスタイムが悪化しています。",
            "メモリリークが発生している可能性があります。",
            "ビルドが失敗しました。",
            "依存関係の問題で動かなくなりました。",
            "セキュリティの脆弱性が見つかりました。",
            "予算がオーバーしそうです。",
            "スケジュールに間に合わないかもしれません。",
        ],
    },
    "acknowledgment": {
        "reactions": ["eyes", "ok", "white_check_mark", "ok_hand", "memo", "bookmark"],
        "messages": [
            "確認しました。",
            "了解です。",
            "承知しました。対応します。",
            "チェックしておきます。",
            "後で確認します。",
            "レビューリクエストを受け取りました。",
            "タスクを割り当てました。",
            "ミーティングの日程、確認しました。",
            "ドキュメントを更新しておきます。",
            "次のスプリントで対応予定です。",
            "優先度を上げて対応します。",
            "調査中です。",
            "進捗報告します。現在50%完了です。",
            "この件、引き続き対応します。",
            "チケットを作成しました。",
        ],
    },
    "humor": {
        "reactions": ["laughing", "joy", "rofl", "smile", "grin", "stuck_out_tongue"],
        "messages": [
            "笑",
            "ウケる",
            "それはひどいww",
            "まさかのオチでしたね",
            "金曜日だ！週末を楽しみましょう",
            "コーヒーが足りない...",
            "会議が長すぎて眠くなってきた",
            "バグじゃなくて仕様です（キリッ",
            "動いているけど理由がわからない",
            "本番で初めて気づくバグあるある",
            "「すぐ終わる」は信用しない",
            "ドキュメント？そんなものはない",
            "前任者の気持ちがわかってきた",
            "マージコンフリクト地獄",
        ],
    },
    "question": {
        "reactions": ["thinking_face", "question", "raising_hand", "mag"],
        "messages": [
            "この仕様について質問があります。",
            "どなたか詳しい方いますか？",
            "このエラーの原因わかる方いますか？",
            "環境構築の手順を教えてください。",
            "この変更の影響範囲はどこまでですか？",
            "レビューをお願いできますか？",
            "このライブラリの使い方がわかりません。",
            "デプロイ手順を確認させてください。",
            "なぜこの実装になっているのでしょうか？",
            "他に良い方法はありますか？",
        ],
    },
    "urgent": {
        "reactions": ["rotating_light", "warning", "exclamation", "bangbang", "sos"],
        "messages": [
            "緊急！本番障害が発生しています！",
            "至急対応お願いします！",
            "重要：セキュリティアップデートが必要です",
            "本番環境で503エラーが多発しています",
            "データベースの接続が切れています",
            "決済処理が止まっています！",
            "ユーザーからのクレームが入っています",
            "サービス復旧を最優先でお願いします",
        ],
    },
}

# 仮想ユーザー
USERS = [
    {"id": "U001TEST", "username": "tanaka", "name": "田中太郎", "real_name": "田中太郎"},
    {"id": "U002TEST", "username": "yamada", "name": "山田花子", "real_name": "山田花子"},
    {"id": "U003TEST", "username": "suzuki", "name": "鈴木一郎", "real_name": "鈴木一郎"},
    {"id": "U004TEST", "username": "sato", "name": "佐藤美咲", "real_name": "佐藤美咲"},
    {"id": "U005TEST", "username": "ito", "name": "伊藤健太", "real_name": "伊藤健太"},
    {"id": "U006TEST", "username": "watanabe", "name": "渡辺由美", "real_name": "渡辺由美"},
    {"id": "U007TEST", "username": "takahashi", "name": "高橋誠", "real_name": "高橋誠"},
    {"id": "U008TEST", "username": "kobayashi", "name": "小林恵", "real_name": "小林恵"},
]

# 仮想チャンネル
CHANNELS = [
    {"id": "C001TEST", "name": "general", "is_private": 0, "is_im": 0, "is_mpim": 0},
    {"id": "C002TEST", "name": "development", "is_private": 0, "is_im": 0, "is_mpim": 0},
    {"id": "C003TEST", "name": "random", "is_private": 0, "is_im": 0, "is_mpim": 0},
    {"id": "C004TEST", "name": "alerts", "is_private": 0, "is_im": 0, "is_mpim": 0},
]


def create_schema(conn: sqlite3.Connection) -> None:
    """データベーススキーマを作成"""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT,
            name TEXT,
            real_name TEXT
        );

        CREATE TABLE IF NOT EXISTS channels (
            id TEXT PRIMARY KEY,
            name TEXT,
            is_private INTEGER,
            is_im INTEGER,
            is_mpim INTEGER
        );

        CREATE TABLE IF NOT EXISTS messages (
            ts TEXT PRIMARY KEY,
            channel_id TEXT,
            user TEXT,
            text TEXT,
            thread_ts TEXT,
            reply_count INTEGER
        );

        CREATE TABLE IF NOT EXISTS reactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_ts TEXT,
            name TEXT,
            user TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_messages_channel ON messages(channel_id);
        CREATE INDEX IF NOT EXISTS idx_reactions_message ON reactions(message_ts);
        CREATE INDEX IF NOT EXISTS idx_reactions_name ON reactions(name);
    """
    )
    conn.commit()


def generate_timestamp() -> str:
    """Slackスタイルのタイムスタンプを生成"""
    base_time = time.time() - random.randint(0, 30 * 24 * 60 * 60)  # 過去30日
    return f"{base_time:.6f}"


def insert_users(conn: sqlite3.Connection) -> None:
    """ユーザーを挿入"""
    for user in USERS:
        conn.execute(
            "INSERT OR REPLACE INTO users(id, username, name, real_name) VALUES(?,?,?,?)",
            (user["id"], user["username"], user["name"], user["real_name"]),
        )


def insert_channels(conn: sqlite3.Connection) -> None:
    """チャンネルを挿入"""
    for channel in CHANNELS:
        conn.execute(
            "INSERT OR REPLACE INTO channels(id, name, is_private, is_im, is_mpim) VALUES(?,?,?,?,?)",
            (
                channel["id"],
                channel["name"],
                channel["is_private"],
                channel["is_im"],
                channel["is_mpim"],
            ),
        )


def generate_messages_and_reactions(
    conn: sqlite3.Connection,
    messages_per_category: int = 50,
    noise_ratio: float = 0.1,
) -> tuple[int, int]:
    """メッセージとリアクションを生成

    Args:
        conn: データベース接続
        messages_per_category: カテゴリごとのメッセージ数
        noise_ratio: ノイズとして別カテゴリのリアクションを付ける割合

    Returns:
        (生成したメッセージ数, 生成したリアクション数)
    """
    message_count = 0
    reaction_count = 0

    for category_name, category_data in CATEGORIES.items():
        messages = category_data["messages"]
        reactions = category_data["reactions"]

        for _ in range(messages_per_category):
            # メッセージ生成
            ts = generate_timestamp()
            channel = random.choice(CHANNELS)
            author = random.choice(USERS)
            text = random.choice(messages)

            # メッセージを少しバリエーションを持たせる
            if random.random() < 0.3:
                text = text + f" #{uuid.uuid4().hex[:6]}"

            conn.execute(
                "INSERT OR REPLACE INTO messages(ts, channel_id, user, text, thread_ts, reply_count) VALUES(?,?,?,?,?,?)",
                (ts, channel["id"], author["id"], text, None, 0),
            )
            message_count += 1

            # リアクション生成（1-3個）
            num_reactions = random.randint(1, 3)
            reactors = random.sample(USERS, min(num_reactions, len(USERS)))

            for reactor in reactors:
                # 通常は該当カテゴリのリアクション
                if random.random() < noise_ratio:
                    # ノイズとして別カテゴリのリアクション
                    other_category = random.choice(
                        [c for c in CATEGORIES.keys() if c != category_name]
                    )
                    reaction_name = random.choice(CATEGORIES[other_category]["reactions"])
                else:
                    reaction_name = random.choice(reactions)

                conn.execute(
                    "INSERT INTO reactions(message_ts, name, user) VALUES(?,?,?)",
                    (ts, reaction_name, reactor["id"]),
                )
                reaction_count += 1

    return message_count, reaction_count


def main():
    parser = argparse.ArgumentParser(description="検証用リアクションデータを生成")
    parser.add_argument(
        "--db-path",
        type=str,
        default="data/test_reactions.db",
        help="出力先データベースパス (default: data/test_reactions.db)",
    )
    parser.add_argument(
        "--messages-per-category",
        type=int,
        default=50,
        help="カテゴリごとのメッセージ数 (default: 50)",
    )
    parser.add_argument(
        "--noise-ratio",
        type=float,
        default=0.1,
        help="ノイズリアクションの割合 (default: 0.1)",
    )
    args = parser.parse_args()

    # ディレクトリ作成
    db_path = Path(args.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # 既存DBがあれば削除
    if db_path.exists():
        db_path.unlink()
        print(f"Removed existing database: {db_path}")

    # DB接続
    conn = sqlite3.connect(str(db_path))

    print("Creating schema...")
    create_schema(conn)

    print("Inserting users...")
    insert_users(conn)

    print("Inserting channels...")
    insert_channels(conn)

    print("Generating messages and reactions...")
    msg_count, react_count = generate_messages_and_reactions(
        conn,
        messages_per_category=args.messages_per_category,
        noise_ratio=args.noise_ratio,
    )

    conn.commit()
    conn.close()

    print(f"\nGenerated test data:")
    print(f"  Users: {len(USERS)}")
    print(f"  Channels: {len(CHANNELS)}")
    print(f"  Categories: {len(CATEGORIES)}")
    print(f"  Messages: {msg_count}")
    print(f"  Reactions: {react_count}")
    print(f"\nDatabase saved to: {db_path}")

    # 統計を表示
    print("\nCategory statistics:")
    for cat_name, cat_data in CATEGORIES.items():
        print(f"  {cat_name}: {len(cat_data['reactions'])} reactions, {len(cat_data['messages'])} message templates")


if __name__ == "__main__":
    main()

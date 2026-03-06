import os
import logging
import threading
from datetime import datetime
from dotenv import load_dotenv

from flask import Flask, request
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from notion_client import Client

# 1. .env ファイルから環境変数を読み込む
load_dotenv()

SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SLACK_APP_TOKEN = os.environ.get("SLACK_APP_TOKEN")
SLACK_CHANNEL_ID = os.environ.get("SLACK_CHANNEL_ID")
NOTION_API_KEY = os.environ.get("NOTION_API_KEY")
NOTION_DATABASE_ID = os.environ.get("NOTION_DATABASE_ID")

# ログの設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Slack Bolt アプリの初期化
app = App(token=SLACK_BOT_TOKEN)

# 全てのリクエストをログ出力するデバッグ用設定
@app.middleware
def log_request(logger, body, next):
    logger.info(f"⚡ Slackから何らかのデータを受信しました！ イベント種類: {body.get('event', {}).get('type')} / チャンネル: {body.get('event', {}).get('channel')}")
    return next()

# Notion クライアントの初期化
notion = Client(auth=NOTION_API_KEY)

# 2. Slack Events API を使用してメッセージ投稿をリアルタイムに検知する
@app.event("message")
def handle_message_events(body, logger, client):
    event = body.get("event", {})
    
    # 特定のチャンネル（SLACK_CHANNEL_ID）に限定
    channel = event.get("channel")
    if channel != SLACK_CHANNEL_ID:
        return
    
    # メッセージの変更など、サブタイプのイベントは無視する
    if "subtype" in event:
        return

    text = event.get("text")
    user_id = event.get("user")
    ts = event.get("ts") # タイムスタンプ
    
    if not text or not user_id:
        return

    try:
        # Slackから投稿者のユーザー情報を取得
        user_info = client.users_info(user=user_id)
        user_name = user_info["user"].get("real_name") or user_info["user"].get("name")
        
        # タイムスタンプを Notion で解釈可能な ISO 8601 形式に変換
        post_datetime = datetime.fromtimestamp(float(ts)).isoformat()

        # 3. Notion API を使用してデータベースに保存する
        # Titleとして、「メッセージ内容 (by ユーザー名)」 という形式にするか、本文そのものを入れます。
        # ここではメッセージ本文を Title に入れ、わかりやすさを優先します
        # 注: Notion側のプロパティ名が "Title" と "Date" であることを前提としています
        
        title_content = f"{text}\n\n-- 投稿者: {user_name}"
        
        notion.pages.create(
            parent={"database_id": NOTION_DATABASE_ID},
            properties={
                "Title": {
                    "title": [
                        {
                            "text": {
                                "content": title_content
                            }
                        }
                    ]
                },
                "Date": {
                    "date": {
                        "start": post_datetime
                    }
                }
            }
        )
        logger.info(f"Notionデータベースに新しいページを追加しました: {text[:20]}...")
        
    except Exception as e:
        logger.error(f"エラーが発生しました: {e}")

# ダミーのWebサーバー（Renderのポートバインディング要件を満たすため）
flask_app = Flask(__name__)

@flask_app.route("/")
def hello():
    return "Bot is running!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    # 環境変数のチェック
    required_env_vars = [
        "SLACK_BOT_TOKEN", 
        "SLACK_APP_TOKEN", 
        "SLACK_CHANNEL_ID", 
        "NOTION_API_KEY", 
        "NOTION_DATABASE_ID"
    ]
    
    missing_vars = [var for var in required_env_vars if not os.environ.get(var)]
    if missing_vars:
        logger.error(f"必要な環境変数が設定されていません: {', '.join(missing_vars)}")
    else:
        logger.info("Starting Flask server for Render health checks...")
        # Flaskを別スレッドで起動
        threading.Thread(target=run_flask, daemon=True).start()
        
        logger.info("Bot is starting in Socket Mode...")
        # Socket Mode を使用してリアルタイムでイベントを受け取る
        SocketModeHandler(app, SLACK_APP_TOKEN).start()

import os
from dotenv import load_dotenv
from google.cloud import aiplatform # 👈 改用 aiplatform 進行基礎設定

load_dotenv()

PROJECT_ID = os.getenv("GCP_PROJECT_ID")
LOCATION = os.getenv("GCP_LOCATION", "asia-east1") # 路由與生成建議用亞洲區
DATA_STORE_LOCATION = os.getenv("DATA_STORE_LOCATION", "global") # Search 通常在 global
DATA_STORE_ID = os.getenv("DATA_STORE_ID")

# 使用最新標準初始化
if PROJECT_ID:
    aiplatform.init(project=PROJECT_ID, location=LOCATION)
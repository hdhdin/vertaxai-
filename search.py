import streamlit as st
from google.oauth2 import service_account
from google.cloud import discoveryengine_v1beta as discoveryengine
import re

def get_clients():
    # 讀取我們稍後會貼在 Secrets 的 gcp_service_account 資訊
    creds_info = st.secrets["gcp_service_account"]
    credentials = service_account.Credentials.from_service_account_info(creds_info)
    
    # 建立搜尋用的 Client
    search_client = discoveryengine.SearchServiceClient(credentials=credentials)
    # 建立文件管理用的 Client (列出清單、算總數用)
    doc_client = discoveryengine.DocumentServiceClient(credentials=credentials)
    
    return search_client, doc_client
# 直接從 st.secrets 讀取，部署時會設定在 Streamlit Cloud 網頁後台
PROJECT_ID = st.secrets["PROJECT_ID"]
LOCATION = st.secrets["LOCATION"]
DATA_STORE_ID = st.secrets["DATA_STORE_ID"]

def list_all_documents():
    """專為無結構 Data Store 設計的檔案清單抓取"""
    try:
        
        _, doc_client = get_clients()
        
        # 使用 default_branch
        parent = f"projects/{PROJECT_ID}/locations/{LOCATION}/dataStores/{DATA_STORE_ID}/branches/default_branch"
        
        request = discoveryengine.ListDocumentsRequest(parent=parent, page_size=100)
        page_result = doc_client.list_documents(request=request)
        
        file_names = []
        for doc in page_result:
            # 對於無結構資料，檔名通常藏在 content.uri 中
            # 格式通常是 gs://bucket_name/folder/filename.pdf
            uri = getattr(doc.content, 'uri', "")
            
            if uri:
                # 取得路徑最後一部分作為檔名
                name = uri.split('/')[-1]
                file_names.append(name)
            else:
                # 如果連 URI 都拿不到，就回傳系統生成的 ID (作為最後手段)
                file_names.append(f"System_ID: {doc.id}")
        
        # 過濾掉重複項並排序
        unique_files = sorted(list(set(file_names)))
        return unique_files if unique_files else ["⚠️ 目前資料庫中無文件"]
        
    except Exception as e:
        # 將錯誤印在終端機供 Debug
        print(f"List Documents Error: {e}")
        return [f"❌ 無法讀取清單: {str(e)}"]

def get_data_store_stats():
    """動態獲取 Data Store 中的文件總數"""
    try:
        # 建立 DocumentServiceClient
        _, doc_client = get_clients()
        
        # Data Store 的完整路徑
        parent = f"projects/{PROJECT_ID}/locations/{LOCATION}/dataStores/{DATA_STORE_ID}/branches/0"
        
        # 獲取文件列表並計算總數 (Vertex AI Search API)
        request = discoveryengine.ListDocumentsRequest(parent=parent, page_size=100)
        page = doc_client.list_documents(request=request)
        
        # 計算總數
        count = sum(1 for _ in page)
        return count
    except Exception as e:
        print(f"Stats Error: {e}")
        return "N/A" # 若抓取失敗則顯示 N/A
    
def super_clean_response(ai_text, search_results):
    if not ai_text:
        return ""
    
    final_text = ai_text
    
    # 1. 先全局清除 AI 文字中常見的系統雜訊前綴，讓文字變乾淨
    # 這樣 "Microsoft Word - HO6..." 就會變成 "HO6..."
    noise_pattern = r"(Microsoft\s*Word\s*-\s*|Adobe\s*PDF\s*-\s*|docx\s*-\s*)"
    final_text = re.sub(noise_pattern, "", final_text, flags=re.IGNORECASE)

    # 2. 建立動態替換清單
    mappings = []
    for result in search_results:
        # Vertex AI Search 的數據結構
        data = result.document.derived_struct_data
        
        # 真實檔名 (從 link 拿，這是絕對正確的)
        actual_name = data.get('link', '').split('/')[-1]
        #print(f"Debug: 真實檔名從 link 解析得到 -> {actual_name}")
        # AI 可能會參考的錯誤標題
        raw_title = data.get('title', '')
        
        # 重要：我們也要把錯誤標題裡的雜訊先洗掉，才能跟第一步洗過的文字對齊
        clean_wrong_title = re.sub(noise_pattern, "", raw_title, flags=re.IGNORECASE)
        
        if clean_wrong_title and clean_wrong_title != actual_name:
            mappings.append((clean_wrong_title, actual_name))

    # 3. 排序：標題越長的先取代，避免短字串誤殺 (例如 'HO' 誤殺 'HO5')
    mappings.sort(key=lambda x: len(x[0]), reverse=True)

    # 4. 執行「正確檔名」覆蓋
    for wrong_part, right_name in mappings:
        if wrong_part in final_text:
            final_text = final_text.replace(wrong_part, right_name)

    # 5. 最後防線：處理頁碼格式並美化
    # 移除重複的括號或清理殘留亂碼
    final_text = re.sub(r'\[\s*:', '[:', final_text) 
    
    return final_text

def run_insurance_engine(query, custom_format=None):
    search_client , _ = get_clients()
    # --- 這是你要求的：嚴格限制與比較邏輯 ---
    strict_instruction = f"""
    # 角色
    你是一位保險經紀人專家，特長是閱讀保險商品文件，熟悉各種保險知識，包括法務相關知識，之後能根據使用者提問提供專業建議。
    你手中有23份文件。你的任務是進行橫向對比分析。

    # 任務執行與衝突處理
    - 若品牌與代號在【檔案名稱】中可對應（如：遠雄HO5、台銀1U），無視內文雜訊，必須直接生成比較表格。
    - 只有在品牌完全配錯（如：全球HO5）時，才輸出：「經查證，[代號] 屬 [正確公司] 而非 [錯誤公司]，請問是否要搜尋正確組合？」並停止畫表。

    # 表格規範 (防止空白關鍵)
    - 必須使用Markdown表格。儲存格內容必須簡潔。
    - **填充規則**：若該商品文件未提及某項數據，請統一填寫「搜尋不到相關數據」。
    - **嚴禁留空**：儲存格不可只有空格、不可填寫 "-"、不可填寫 "null"。
    - **禁止對齊**：生成Markdown時請勿為了美觀而補入額外的連續空格。

    # 檔案校正與來源
    - 檔名即真理：從'link'提取檔名。若文件寫HO6但檔名是HO5，請校正為HO5。
    - 表格內禁止標註來源。
    - 請統一於結尾呈現「參考文件清單」，列出所有參考過的檔案名稱與頁碼，要有對應代碼呈現。
    - 格式：* 【原始檔案名稱】 (第N頁)。
    """

    serving_config = search_client.serving_config_path(
        project=PROJECT_ID, location=LOCATION, 
        data_store=DATA_STORE_ID, serving_config="default_search"
    )

    # 增加參考區塊數量，確保 A 與 B 都能被讀取
    content_search_spec = {
        "summary_spec": {
            "summary_result_count": 10, # 提高數量以支持 A/B 比較
            "include_citations": True,
            "ignore_adversarial_query": True,
            "model_prompt_spec": {"preamble": strict_instruction},
        }
    }

    request = discoveryengine.SearchRequest(
        serving_config=serving_config,
        query=query,
        content_search_spec=content_search_spec
    )

    response = search_client.search(request)
    summary_text = response.summary.summary_text if response.summary else "搜尋失敗"
    return summary_text, response.results

if __name__ == "__main__":
    # 測試指令
    test_comparison_query = "請比較安聯WPD1與台銀人壽1X的除外責任"

    # "請比較『台銀人壽 (1U)』與『遠雄人壽永安手術 (HO5)』的手術給付邏輯（包含是否有無理賠增值優待）以及投保年齡限制。"
    # "請比較『台銀人壽 (1U)』與『全球人壽 (HO5)』的手術給付邏輯（包含是否有無理賠增值優待）以及投保年齡限制。"
    # "請比較『台銀人壽 (1U)』與『遠雄人壽永安手術 (HO5)』的投保年齡限制。"

    # 執行測試
    print("🔍 正在進行第一步壓力測試：嚴格溯源與禁止推論...")
    raw_result, search_data = run_insurance_engine(test_comparison_query)
    clean_result = super_clean_response(raw_result, search_data)  # 目前沒有傳入搜尋結果，僅示範替換邏輯

    print("\n--- 輸出結果 ---")
    print(clean_result)

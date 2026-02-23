import streamlit as st
import re
from search import run_insurance_engine, super_clean_response ,get_data_store_stats,list_all_documents # 請確保檔名正確

DATA_STORE_ID = st.secrets["DATA_STORE_ID"]

# --- 頁面配置 ---
st.set_page_config(page_title="AI 保險合規審查助手", layout="wide", page_icon="⚖️")
# 定義快取函數，每小時更新一次即可
@st.cache_data(ttl=600)
def fetch_total_docs():
    count = get_data_store_stats()
    files = list_all_documents()
    return count, files

total_docs, file_list = fetch_total_docs()
# --- 自定義 CSS ---
st.markdown("""
    <style>
    .stTable { font-size: 14px; }
    .highlight { color: #ff4b4b; font-weight: bold; }
    </style>
""", unsafe_allow_html=True)


# --- 側邊欄：知識庫概覽 ---
with st.sidebar:
    st.title("⚖️ 系統監測")
    
    # 動態顯示文件數量
    st.success(f"📂 目前已掛載 {total_docs} 份保險條款")
    # 這是你要的小工具：檔案清單
    with st.expander("📋 檢視所有已掛載檔案"):
        st.caption("點擊下方名稱可直接複製，用於測試 Query")
        if file_list:
            for f in file_list:
                # 使用 code 格式方便使用者點選複製
                st.code(f, language=None)
        else:
            st.warning("無法取得")
            
    if st.button("🔄 強制重新整理文件清單"):
        st.cache_data.clear()
        st.rerun()

    st.divider()
    if st.button("🔄 重置對話環境"):
        st.session_state.messages = []
        st.rerun()

# --- 主界面 ---
st.title("🔍 保險商品橫向對比分析")
st.caption(f"當前掃描範圍：Data Store - {DATA_STORE_ID}")

# 初始化對話紀錄
if "messages" not in st.session_state:
    st.session_state.messages = []

# 顯示過去的對話
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# --- 使用者輸入 ---
if prompt := st.chat_input("請輸入比較需求..."):
    
    # 1. 顯示使用者問題
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # 2. AI 思考與執行
    with st.chat_message("assistant"):
        with st.status(f"🔮 正在從 {total_docs} 份條款中檢索關鍵證據...", expanded=True) as status:
            try:
                # 執行後端邏輯
                raw_text, search_results = run_insurance_engine(prompt)
                
                # 執行超級清洗
                clean_text = super_clean_response(raw_text, search_results)
                
                # 強制二次清洗連續空白 (前端防線)
                final_output = re.sub(r' +', ' ', clean_text)
                final_output = final_output.replace('| |', '| 搜尋不到相關數據 |')
                
                status.update(label="✅ 分析完成！", state="complete", expanded=False)
                
                # 渲染結果
                st.markdown(final_output)
                st.session_state.messages.append({"role": "assistant", "content": final_output})
                
            except Exception as e:
                status.update(label="❌ 處理發生錯誤", state="error")
                st.error(f"系統暫時無法處理您的請求。錯誤資訊：{str(e)}")

# --- 底部提示 ---
st.divider()
st.caption("註：本系統僅提供條款數據對照，具體承保規則請以保險公司最新公告為準。")
import streamlit as st
import os
import re
import pdfplumber
import gspread
from google.oauth2.service_account import Credentials

# --- 1. पेज सेटिंग्स ---
st.set_page_config(page_title="CK CUSTOM EXAMINATION AUTOMATION", page_icon="⚙️", layout="wide")
st.title("⚙️ CK CUSTOM EXAMINATION AUTOMATION")
st.subheader("Adani Invoices Automatic Data Importer")
st.markdown("---")

# --- 2. गूगल शीट कनेक्शन (परमानेंट तरीका) ---
@st.cache_resource
def connect_google_sheet():
    try:
        scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        
        # यह सीधे स्ट्रीमलिट के सीक्रेट्स बॉक्स से डेटा उठाएगा
        info_dict = dict(st.secrets["gcp_service_account"])
        
        # \n को असली न्यूलाइन में बदलेगा
        info_dict["private_key"] = info_dict["private_key"].replace("\\n", "\n")
        
        creds = Credentials.from_service_account_info(info_dict, scopes=scope)
        gc = gspread.authorize(creds)
        spreadsheet_id = "1lEIV6Bcvo7CsiBYWeqURT1PUuvQvoypw6VF92Aq2lcc"
        sh = gc.open_by_key(spreadsheet_id)
        return sh.sheet1
    except Exception as e:
        st.error(f"❌ गूगल शीट कनेक्ट नहीं हो सकी: {e}")
        return None

worksheet = connect_google_sheet()

# --- 3. पीडीएफ से डेटा निकालने का लॉजिक ---
def process_single_pdf(pdf_file):
    full_text = ""
    tables_data = []
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            text_content = page.extract_text()
            if text_content: full_text += "\n" + text_content
            extracted_tables = page.extract_tables()
            for table in extracted_tables: tables_data.append(table)
                
    exp_match = re.search(r"Exporter\s+Name\s*:\s*(.*)", full_text, re.IGNORECASE)
    exporter_name = exp_match.group(1).strip() if exp_match else ""
    
    sb_match = re.search(r"SB\s+No\s*:\s*(\d{7})|SB\s+No\s+(\d{7})", full_text, re.IGNORECASE)
    sb_no = sb_match.group(1) if sb_match and sb_match.group(1) else (sb_match.group(2) if sb_match else "")
        
    inv_match = re.search(r"Invoice\s+No\s*:\s*(\w+)|Invoice\s+Number\s*:\s*(\w+)", full_text, re.IGNORECASE)
    invoice_no = inv_match.group(1) if inv_match and inv_match.group(1) else (inv_match.group(2) if inv_match else "")
        
    condition_val = ""
    if invoice_no.startswith("MIE"): condition_val = "Buffer"
    elif invoice_no.startswith("MCP"):
        if "0-25%" in full_text: condition_val = "First Slab < 25%"
        elif "25-50%" in full_text: condition_val = "Second Slab 25-50%"
        elif "above 50%" in full_text: condition_val = "Third Slab > 50%"

    containers, sizes = [], []
    for table in tables_data:
        for row in table:
            row_clean = [str(cell).strip() for cell in row if cell is not None]
            for cell in row_clean:
                if re.match(r"^[A-Z]{4}\d{7}$", cell):
                    if cell not in containers:
                        containers.append(cell)
                        if "20" in row_clean: sizes.append("20 Feet")
                        elif "40" in row_clean or "45" in row_clean: sizes.append("40 Feet")
                        else: sizes.append("")

    container_no_str = ", ".join(containers) if containers else ""
    unique_sizes = list(set([s for s in sizes if s]))
    size_str = ", ".join(unique_sizes) if unique_sizes else ""
    container_count = len(containers) if containers else 0
    
    taxable_amount, igst_amount, total_bill_amount = 0.0, 0.0, 0.0
    tax_match = re.search(r"Total\s+Tax\s+Value\s*\(In\s+figure\)\s*:\s*([\d\.,]+)", full_text, re.IGNORECASE)
    if tax_match: igst_amount = float(tax_match.group(1).replace(',', '').strip())
        
    bill_match = re.search(r"Total\s+Invoice\s+Value\s*\(In\s+figure\)\s*:\s*([\d\.,]+)", full_text, re.IGNORECASE)
    if bill_match: total_bill_amount = float(bill_match.group(1).replace(',', '').strip())

    for table in tables_data:
        if len(table) > 1:
            for row in table:
                row_clean = [str(cell).strip() for cell in row if cell is not None]
                if any("total" in str(cell).lower() for cell in row_clean):
                    numbers_in_row = [float(c.replace(',', '').strip()) for c in row_clean if re.match(r"^\d+(\.\d+)?$", c.replace(',', '').strip())]
                    if numbers_in_row: taxable_amount = numbers_in_row[0]
                    break
            if taxable_amount > 0: break

    if taxable_amount == 0.0 and total_bill_amount > 0: taxable_amount = round(total_bill_amount - igst_amount, 2)
    col_n_val = round(taxable_amount * 0.02, 2)
    col_o_val = round(total_bill_amount - col_n_val, 2)
    
    return {"B": exporter_name, "C": "", "D": "", "E": sb_no, "F": "", "G": container_no_str, "H": condition_val, 
            "I": size_str, "J": container_count, "K": taxable_amount, "L": igst_amount, "M": total_bill_amount, 
            "N": col_n_val, "O": col_o_val, "P": invoice_no}

# --- 4. यूज़र इंटरफेस लेआउट ---
col1, col2 = st.columns([1, 1])

with col1:
    st.markdown("### 📁 ऑप्शन 1: मैन्युअल अपलोड")
    uploaded_files = st.file_uploader("मिसिंग इनवॉउस (PDF फाइल्स) यहाँ चुनें:", type="pdf", accept_multiple_files=True)

with col2:
    st.markdown("### 📥 ऑप्शन 2: ईमेल से डायरेक्ट फेच")
    st.info("Gmail से 'Adani Invoices' सीधे सिंक करने के लिए नीचे क्लिक करें")
    gmail_btn = st.button("🔄 Fetch & Import from Gmail", type="secondary", use_container_width=True)

if uploaded_files and worksheet is not None:
    if st.button("🚀 Start Manual Import", type="primary", use_container_width=True):
        with st.spinner("प्रोसेसिंग जारी है..."):
            all_existing_rows = worksheet.get_all_values()
            current_rows_count = len(all_existing_rows)
            existing_invoices = set(row[15].strip() for row in all_existing_rows[1:] if len(row) > 15 and row[15])
            
            all_rows_to_append = []
            duplicate_count = 0
            
            for u_file in uploaded_files:
                try:
                    data = process_single_pdf(u_file)
                    inv_no = str(data["P"]).strip()
                    if inv_no in existing_invoices or any(r["P"] == inv_no for r in all_rows_to_append): 
                        duplicate_count += 1
                    else: 
                        all_rows_to_append.append(data)
                except Exception as e:
                    st.error(f"त्रुटि: {e}")
                    
            if all_rows_to_append:
                sheet_format_data = [[current_rows_count+idx+1, d["B"], "", "", d["E"], "", d["G"], d["H"], d["I"], d["J"], d["K"], d["L"], d["M"], d["N"], d["O"], d["P"], "", "", "", "", ""] for idx, d in enumerate(all_rows_to_append)]
                worksheet.append_rows(sheet_format_data)
                st.success(f"🎉 सफलतापूर्वक {len(sheet_format_data)} इनवॉइस इम्पोर्ट हो गए हैं!")
            else:
                st.info("ℹ️ कोई नया डेटा आयात नहीं हुआ।")
            if duplicate_count > 0:
                st.warning(f"⚠️ {duplicate_count} डुप्लीकेट स्किप किए गए।")

if gmail_btn:
    st.warning("Gmail सिंक फ़ीचर एक्टिवेट हो रहा है...")

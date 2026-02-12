
import pdfplumber
import sys
from pathlib import Path

PDF_PATH = r"e:\Automation\30XW_tcm177-84440.pdf"

def debug_pdf():
    print(f"Opening {PDF_PATH}...")
    try:
        with pdfplumber.open(PDF_PATH) as pdf:
            # Page 6 is index 5
            page = pdf.pages[5]
            print(f"Page 6 dimensions: {page.width}x{page.height}")
            
            # Try default extraction
            print("\n--- Default Extraction ---")
            tables = page.extract_tables()
            print(f"Found {len(tables)} tables.")
            if tables:
                print(f"First table rows: {len(tables[0])}")
                print(tables[0][:3])
                
            # Try text strategy
            print("\n--- Text Strategy ---")
            settings = {
                "vertical_strategy": "text", 
                "horizontal_strategy": "text",
                "snap_tolerance": 3,
            }
            tables_text = page.extract_tables(table_settings=settings)
            print(f"Found {len(tables_text)} tables.")
            if tables_text:
                print(f"First table rows: {len(tables_text[0])}")
                print(tables_text[0][:3])
                
            # Try explicit lines if visual debug
            # (Can't do visual, but can check if lines detected)
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    debug_pdf()

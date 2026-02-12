
import pymupdf
import sys
import os

pdf_path = "30XW_tcm177-84440.pdf"

if not os.path.exists(pdf_path):
    print(f"PDF not found: {pdf_path}")
    sys.exit(1)

doc = pymupdf.open(pdf_path)
print(f"Opened {pdf_path}, pages: {len(doc)}")

for i in [5, 6, 7, 8]: # Check pages 6-9 (0-indexed 5-8) where tables are
    if i >= len(doc): break
    page = doc[i]
    tables = page.find_tables()
    print(f"\n--- Page {i+1} ---")
    if tables.tables:
        print(f"Found {len(tables.tables)} tables.")
        for table in tables:
            print(table.extract()[:2]) # Print first 2 rows
    else:
        print("No tables found via pymupdf.")

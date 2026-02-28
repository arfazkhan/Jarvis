
import os

path = 'glass_box_audit.jsonl'
if os.path.exists(path):
    with open(path, 'rb') as f:
        content = f.read()
    
    encodings = ['utf-8', 'utf-16-le', 'utf-16-be', 'utf-16']
    decoded = None
    for enc in encodings:
        try:
            decoded = content.decode(enc)
            print(f"Successfully decoded with {enc}")
            break
        except:
            continue
            
    if decoded:
        # Standardize to utf-8
        with open(path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(decoded)
        print("Standardized to UTF-8")
    else:
        print("Failed to decode with any standard encoding")
else:
    print(f"File {path} not found")

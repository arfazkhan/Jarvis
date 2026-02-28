
import os

path = 'glass_box_audit.jsonl'
if os.path.exists(path):
    print(f"Analyzing {path}...")
    with open(path, 'rb') as f:
        content = f.read()
    
    # Try different encodings
    for enc in ['utf-16-le', 'utf-16', 'utf-8']:
        try:
            decoded = content.decode(enc)
            print(f"Successfully decoded with {enc}")
            # Remove any leading/trailing empty lines or BOM-like artifacts
            lines = [line.strip() for line in decoded.splitlines() if line.strip()]
            
            with open(path, 'w', encoding='utf-8', newline='\n') as f_out:
                for line in lines:
                    f_out.write(line + '\n')
            print(f"Successfully standardized {len(lines)} lines to UTF-8")
            break
        except Exception as e:
            print(f"Failed with {enc}: {e}")
else:
    print(f"File {path} not found")

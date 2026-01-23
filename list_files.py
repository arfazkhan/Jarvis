from huggingface_hub import list_repo_files

repo_id = "unsloth/functiongemma-270m-it-GGUF"
files = list_repo_files(repo_id)
print(f"Files in {repo_id}:")
for f in files:
    print(f)

import os
from huggingface_hub import hf_hub_download
from llama_cpp import Llama

# 1. Download Model
model_name = "ggml-org/functiongemma-270m-it-GGUF"
model_file = "functiongemma-270m-it-q8_0.gguf" # Using q8_0 (only available quantized)
print(f"Downloading {model_name}...")

model_path = hf_hub_download(repo_id=model_name, filename=model_file)
print(f"Model downloaded to: {model_path}")

# 2. Load Model
print("Loading model...")
llm = Llama(
    model_path=model_path,
    n_ctx=2048,
    verbose=False
)

# 3. Test Inference
prompt = """<bos><start_of_turn>user
Turn on the kitchen lights.<end_of_turn>
<start_of_turn>model
"""

print("Running inference...")
output = llm(
    prompt, 
    max_tokens=64, 
    stop=["<end_of_turn>"], 
    echo=False
)

print("-" * 50)
print("Input: Turn on the kitchen lights.")
print("Output:", output['choices'][0]['text'])
print("-" * 50)

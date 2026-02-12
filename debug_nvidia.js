import axios from 'axios';
import dotenv from 'dotenv';
import { fileURLToPath } from 'url';
import { dirname, resolve } from 'path';

// Load .env
const __dirname = dirname(fileURLToPath(import.meta.url));
dotenv.config({ path: resolve(__dirname, '.env') });

const invokeUrl = "https://integrate.api.nvidia.com/v1/chat/completions";
const stream = true;

const apiKey = process.env.NVIDIA_API_KEY;

if (!apiKey) {
    console.error("❌ Error: NVIDIA_API_KEY not found in .env");
    process.exit(1);
}

const headers = {
  "Authorization": `Bearer ${apiKey}`,
  "Accept": stream ? "text/event-stream" : "application/json",
  "Content-Type": "application/json"
};

const payload = {
  "model": "moonshotai/kimi-k2.5",
  "messages": [{"role":"user","content":"What is in this image?"}], // Note: User prompt asks about image but no image provided. Kimi should handle or complain.
  "max_tokens": 16384,
  "temperature": 1.00,
  "top_p": 1.00,
  "stream": stream,
  "chat_template_kwargs": {"thinking":false},
};

console.log(`→ Sending request to ${invokeUrl} (Model: ${payload.model})...`);

axios.post(invokeUrl, payload, {
    headers: headers,
    responseType: stream ? 'stream' : 'json',
    timeout: 30000 // 30s timeout matching previous tests
  })
  .then(response => {
    if (stream) {
      console.log("✅ Receiving Stream:");
      response.data.on('data', (chunk) => {
        console.log(chunk.toString());
      });
      response.data.on('end', () => {
          console.log("\n[Stream Ended]");
      });
    } else {
      console.log(JSON.stringify(response.data));
    }
  })
  .catch(error => {
    if (error.response) {
        console.error(`❌ Status: ${error.response.status}`);
        console.error(`❌ Data:`, error.response.data);
    } else {
        console.error(`❌ Error: ${error.message}`);
    }
  });

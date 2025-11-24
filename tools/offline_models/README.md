# Offline Models Directory

This directory stores locally downloaded AI models for offline operation.

## Models to Download (as needed)

### Phase 1: Cognitive Layer
- Sentence Transformers: `sentence-transformers/all-MiniLM-L6-v2`

### Phase 2: Conversation
- Whisper (Speech-to-Text): `openai/whisper-base`
- Sentiment Analysis: `distilbert-base-uncased-finetuned-sst-2-english` (optional)

### Phase 5: Personality
- Transformers for emotion detection (optional)

## Usage

Models will be automatically downloaded on first use, but you can pre-download them:

```python
from sentence_transformers import SentenceTransformer

# Pre-download embedding model
model = SentenceTransformer('all-MiniLM-L6-v2')
model.save('./tools/offline_models/all-MiniLM-L6-v2')
```

## Storage Estimates
- Sentence Transformers (MiniLM): ~80 MB
- Whisper Base: ~140 MB
- Whisper Small: ~460 MB
- Total (recommended): ~300-600 MB

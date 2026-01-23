# CosyVoice TTS Setup Guide

ARVIS now supports **CosyVoice** as an alternative TTS engine alongside Coqui.

## Quick Start

### Option 1: Use Coqui (Default)
No changes needed - Coqui TTS is the default and works out of the box.

```bash
# .env (or just don't set TTS_ENGINE)
TTS_ENGINE=coqui
```

### Option 2: Use CosyVoice

#### Step 1: Install CosyVoice
```bash
# Clone CosyVoice repository
git clone https://github.com/FunAudioLLM/CosyVoice.git
cd CosyVoice

# Install (requires CUDA)
pip install -e .

# Go back to ARVIS directory
cd ..
```

#### Step 2: Configure Environment
Add to your `.env` file:
```bash
TTS_ENGINE=cosyvoice
COSYVOICE_MODEL=CosyVoice2-0.5B
COSYVOICE_DEVICE=cuda
COSYVOICE_SPEAKER=英文女
```

#### Step 3: Run ARVIS
```bash
python agent/main.py
```

## Configuration Options

| Variable | Values | Description |
|----------|--------|-------------|
| `TTS_ENGINE` | `coqui` (default), `cosyvoice`, `kokoro`, `piper` | TTS backend |
| `COSYVOICE_MODEL` | `CosyVoice2-0.5B` (default) | Model size (~2-3GB VRAM) |
| `COSYVOICE_DEVICE` | `cuda` (default), `cpu` | Processing device |
| `COSYVOICE_SPEAKER` | `英文女` (default) | Speaker voice |

## Available CosyVoice Speakers
- `英文女` - English Female (default)
- `英文男` - English Male
- `中文女` - Chinese Female
- `中文男` - Chinese Male
- `日语男` - Japanese Male
- `韩语女` - Korean Female
- `粤语女` - Cantonese Female

## Comparison

| Feature | Coqui | CosyVoice |
|---------|-------|-----------|
| First-audio latency | ~300ms | ~150ms |
| Languages | Many | 9 languages + dialects |
| VRAM usage | ~1-2GB | ~2-3GB |
| Quality | Good | Excellent |
| Streaming | Yes | Yes (bi-directional) |
| Installation | pip install | Separate git clone |

## Troubleshooting

### CosyVoice not loading
```
CosyVoice not available, falling back to Coqui
```
Make sure you installed CosyVoice correctly:
```bash
cd CosyVoice && pip install -e .
```

### CUDA out of memory
Use the 0.5B model (default) or try CPU:
```bash
COSYVOICE_DEVICE=cpu
```

### Fallback behavior
If CosyVoice fails to initialize, ARVIS automatically falls back to Coqui TTS.

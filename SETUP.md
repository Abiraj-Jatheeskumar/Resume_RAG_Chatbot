# 🚀 Quick Setup Guide

## Prerequisites

- Python 3.8 or higher
- pip (Python package manager)
- (Optional) Tesseract OCR for scanned PDFs

## Step-by-Step Setup

### 1. Clone or Download the Project

```bash
git clone <your-repo-url>
cd RAG
```

### 2. Create Virtual Environment (Recommended)

**Windows:**
```bash
python -m venv venv
venv\Scripts\activate
```

**macOS/Linux:**
```bash
python -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Environment (Optional)

Create a `.env` file in the root directory:

```env
# OpenAI (optional)
OPENAI_API_KEY=your_key_here

# Anthropic Claude (optional)
ANTHROPIC_API_KEY=your_key_here

# Model Selection
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini
EMBEDDING_MODEL=openai
```


---

## Enable Claude Haiku 4.5 for All Clients

To use Anthropic Claude Haiku 4.5 as the LLM for all users:

1. **Get your Anthropic API key:**
	- Go to https://console.anthropic.com/settings/keys
	- Create and copy your API key.

2. **Create or edit your `.env` file in the project root:**
	```env
	ANTHROPIC_API_KEY=your-anthropic-key-here
	LLM_PROVIDER=anthropic
	LLM_MODEL=claude-3-haiku-20240229
	```
	*(Replace with the latest Haiku 4.5 model name if different)*

3. **Restart the app:**
	```powershell
	streamlit run app.py
	```

4. **Verify:**
	- The sidebar should show "Anthropic LLM enabled - Claude Haiku".
	- All chat queries will use Claude Haiku for generation.

No extra code changes are needed—just set the environment variables and restart!

### 5. Install Tesseract OCR (Optional, for scanned PDFs)

**Windows:**
- Download from: https://github.com/UB-Mannheim/tesseract/wiki
- Add to PATH or set `TESSDATA_PREFIX` environment variable

**macOS:**
```bash
brew install tesseract
```

**Ubuntu/Debian:**
```bash
sudo apt-get install tesseract-ocr
```

### 6. Run the Application

```bash
streamlit run app.py
```

The app will open in your browser at `http://localhost:8501`

## Docker Setup (Alternative)

### Using Docker Compose (Recommended)

```bash
docker-compose up --build
```

### Using Docker directly

```bash
docker build -t resume-rag .
docker run -p 8501:8501 resume-rag
```

## Troubleshooting

### Issue: Import errors

**Solution:** Make sure all dependencies are installed:
```bash
pip install -r requirements.txt
```

### Issue: Tesseract not found

**Solution:** Install Tesseract OCR or disable OCR feature

### Issue: Memory errors with large PDFs

**Solution:** 
- Process fewer PDFs at once
- Reduce chunk size in `.env`: `MAX_CHUNK_SIZE=500`

### Issue: API key errors

**Solution:** The system works without API keys. If you want to use OpenAI/Claude:
- Create `.env` file
- Add your API keys
- Restart the application

## Next Steps

1. Upload resume PDFs in the sidebar
2. Click "Process Resumes"
3. Start chatting with your resumes!
4. Explore analytics and export features

## Need Help?

- Check the main README.md for detailed documentation
- Review error logs in `app.log`
- Open an issue on GitHub



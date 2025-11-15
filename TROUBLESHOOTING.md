# 🔧 Troubleshooting Guide

## ✅ Fixed Issues

### 1. Deprecation Warnings Fixed
- ✅ `use_container_width` → Changed to `width='stretch'`
- ✅ `HuggingFaceEmbeddings` → Added support for `langchain-huggingface`

### 2. Azure OpenAI Key Not Loading

**Problem**: Azure OpenAI key exists in `.env` but not being detected

**Possible Causes:**
1. **BOM (Byte Order Mark)** in .env file
2. **Encoding issues** (UTF-8 vs ASCII)
3. **Line ending issues** (Windows vs Unix)
4. **Whitespace** in key value

**Solutions:**

#### Solution 1: Recreate .env File
```powershell
# Delete old .env
Remove-Item .env

# Create new .env (one line at a time)
"AZURE_OPENAI_KEY=your-key-here" | Out-File -FilePath .env -Encoding ASCII
"AZURE_OPENAI_ENDPOINT=your-endpoint" | Out-File -FilePath .env -Encoding ASCII -Append
"AZURE_OPENAI_DEPLOYMENT=gpt-4.1" | Out-File -FilePath .env -Encoding ASCII -Append
"AZURE_OPENAI_API_VERSION=2025-01-01-preview" | Out-File -FilePath .env -Encoding ASCII -Append
"LLM_PROVIDER=azure_openai" | Out-File -FilePath .env -Encoding ASCII -Append
```

#### Solution 2: Check .env File Format
- ✅ No BOM (Byte Order Mark)
- ✅ No quotes around values
- ✅ No trailing spaces
- ✅ One variable per line
- ✅ Format: `KEY=value` (no spaces around `=`)

#### Solution 3: Verify Key is Loading
```python
from dotenv import load_dotenv
import os
load_dotenv(override=True)
print(os.getenv('AZURE_OPENAI_KEY'))  # Should print your key
```

## 🔍 How to Verify Azure OpenAI is Working

### Check 1: Environment Variable
```python
import os
from dotenv import load_dotenv
load_dotenv(override=True)
key = os.getenv('AZURE_OPENAI_KEY')
print(f"Key found: {bool(key)}")
print(f"Key length: {len(key) if key else 0}")
```

### Check 2: Sidebar Status
When you run the app, sidebar should show:
- ✅ "✅ Azure OpenAI LLM enabled - gpt-4.1"

### Check 3: Chat Response
Ask a question - should get AI-generated answer (not raw snippets)

## 🚨 Common Issues

### Issue: "Azure OpenAI provider selected but no API key found"
**Cause**: Key not loading from .env
**Fix**: 
1. Check .env file exists
2. Verify key format (no quotes, no spaces)
3. Restart Streamlit app
4. Check for BOM in file

### Issue: "No LLM provider available"
**Cause**: Azure credentials not properly configured
**Fix**:
1. Verify all 4 Azure variables are set:
   - AZURE_OPENAI_KEY
   - AZURE_OPENAI_ENDPOINT
   - AZURE_OPENAI_DEPLOYMENT
   - AZURE_OPENAI_API_VERSION
2. Check endpoint has no trailing slash (code handles this now)
3. Restart app

### Issue: OCR Failed
**Cause**: Tesseract not installed
**Fix**: 
- Install Tesseract OCR (optional)
- Or just don't use OCR checkbox (works fine without it)

## 📝 Next Steps

1. **Restart Streamlit app** after fixing .env
2. **Check sidebar** for Azure OpenAI status
3. **Test with a question** to verify it's working


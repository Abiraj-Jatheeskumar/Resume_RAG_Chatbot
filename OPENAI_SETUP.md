# 🔑 How to Enable Full RAG with OpenAI API

## Understanding: Basic Retrieval vs Full RAG

### ❌ Without OpenAI Key (Current - Basic Retrieval Only)
- ✅ **Retrieval**: Finds relevant resume sections using vector search
- ❌ **Generation**: NO AI-generated answers - just shows raw document snippets
- This is **NOT** true RAG - it's just **Retrieval** without **Generation**

**What you see:**
```
Found relevant information from 2 candidate(s):

1. John Doe
Email: john@email.com
Relevant sections:
  1. [Raw text from resume]...
  2. [Raw text from resume]...
```

### ✅ With OpenAI Key (Full RAG - Retrieval + Generation)
- ✅ **Retrieval**: Finds relevant resume sections
- ✅ **Generation**: AI synthesizes and creates intelligent answers
- This is **TRUE RAG** - **Retrieval-Augmented Generation**

**What you see:**
```
Based on the resumes, I found 2 candidates with Python experience:

1. **John Doe** - Has 5+ years of Python experience with Django and Flask. 
   Experience includes building REST APIs and web applications.

2. **Jane Smith** - Python developer with machine learning experience using 
   TensorFlow and PyTorch. Has worked on data science projects.
```

## 🚀 Step-by-Step: Enable OpenAI API

### Step 1: Get OpenAI API Key

1. Go to [OpenAI Platform](https://platform.openai.com/)
2. Sign up or log in
3. Navigate to [API Keys](https://platform.openai.com/api-keys)
4. Click "Create new secret key"
5. Copy the key (starts with `sk-...`)
   - ⚠️ **Important**: Save it immediately - you won't see it again!

### Step 2: Create .env File

Create a file named `.env` in your project root directory:

**Windows:**
```powershell
# In PowerShell, navigate to your project folder
cd C:\Users\aabir\OneDrive\Desktop\RAG

# Create .env file
notepad .env
```

**macOS/Linux:**
```bash
cd ~/path/to/RAG
nano .env
```

### Step 3: Add Your API Key

Add this line to your `.env` file:

```env
OPENAI_API_KEY=sk-your-actual-api-key-here
```

**Important:**
- Replace `sk-your-actual-api-key-here` with your actual key
- Do NOT add quotes around the key
- Keep this file secret - never commit it to Git

### Step 4: Restart the Application

1. Stop the Streamlit app (Ctrl+C in terminal)
2. Restart it:
   ```bash
   streamlit run app.py
   ```

### Step 5: Verify It's Working

In the Streamlit sidebar, you should see:
- ✅ **"✅ OPENAI LLM enabled - gpt-4o-mini"** (green message)

When you ask questions, you'll get:
- 🤖 **AI-generated answers** instead of raw text snippets
- 📝 **Synthesized responses** that mention all relevant candidates
- 💬 **Conversational replies** instead of document dumps

## 📋 Example .env File

Create `.env` in your project root with:

```env
# OpenAI Configuration
OPENAI_API_KEY=sk-your-key-here

# Optional: Model Selection
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini

# Optional: Embedding Model
EMBEDDING_MODEL=openai

# Optional: Logging
LOG_LEVEL=INFO
```

## 🔍 Verify Setup

### Check 1: Environment Variable
In Python/terminal:
```python
import os
from dotenv import load_dotenv
load_dotenv()
print(os.getenv("OPENAI_API_KEY")[:10])  # Should show first 10 chars (sk-...)
```

### Check 2: Streamlit Sidebar
When you run `streamlit run app.py`, the sidebar should show:
- ✅ Green message: "✅ OPENAI LLM enabled - gpt-4o-mini"

### Check 3: Chat Response
Ask a question like: "Who has Python experience?"
- **Without API key**: Shows raw text snippets
- **With API key**: Shows AI-generated answer mentioning all candidates

## 💰 OpenAI API Pricing

- **GPT-4o-mini**: ~$0.15 per 1M input tokens, $0.60 per 1M output tokens
- **Cost per query**: Typically $0.001-0.01 (very cheap!)
- **Free tier**: $5 credit when you sign up (expires after 3 months)

## 🛠️ Troubleshooting

### Issue: "No module named 'openai'"
**Solution:**
```bash
pip install openai langchain-openai
```

### Issue: "Invalid API key"
**Check:**
- Key starts with `sk-`
- No spaces or quotes in .env file
- File is named `.env` (not `.env.txt`)
- Restarted the app after adding key

### Issue: "Rate limit exceeded"
**Solution:**
- You've hit OpenAI's rate limit
- Wait a few minutes and try again
- Consider upgrading your OpenAI plan

### Issue: "Still shows basic retrieval"
**Check:**
- .env file is in project root (same folder as app.py)
- File is named exactly `.env` (not `.env.txt` or `env.txt`)
- Restarted Streamlit after creating .env
- Check sidebar for LLM status

## 🎯 What Changes When You Add API Key?

### Before (Basic Retrieval):
```
Q: "Who has Python experience?"
A: Found 2 relevant sections:
   1. From John Doe: Python developer with 5 years...
   2. From Jane Smith: Python, Django, Flask...
```

### After (Full RAG):
```
Q: "Who has Python experience?"
A: Based on the resumes, I found 2 candidates with Python experience:

   1. **John Doe** - Python developer with 5+ years of experience. 
      Has worked with Django and Flask frameworks.

   2. **Jane Smith** - Experienced Python developer with expertise in 
      Django and Flask. Also has machine learning experience.
```

## 📝 Quick Reference

| Feature | Without API Key | With API Key |
|---------|----------------|--------------|
| Search resumes | ✅ Yes | ✅ Yes |
| Show document snippets | ✅ Yes | ✅ Yes |
| AI-generated answers | ❌ No | ✅ Yes |
| Mentions all candidates | ⚠️ Partial | ✅ Always |
| Conversational replies | ❌ No | ✅ Yes |
| True RAG | ❌ No | ✅ Yes |

---

**Need Help?** Check the main README.md or open an issue on GitHub.


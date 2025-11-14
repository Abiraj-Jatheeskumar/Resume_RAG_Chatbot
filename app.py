"""
RAG Chatbot for Resume Search using LangChain and Streamlit.
"""
import os
import re
import streamlit as st
import logging
from typing import List, Dict, Optional
from langchain_core.documents import Document
from langchain_community.vectorstores import FAISS
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
import tempfile
import shutil
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from utils import (
    process_resume_pdf,
    get_embeddings,
    get_llm,
    create_vector_store,
    load_vector_store,
    chunk_text,
    save_metadata,
    load_metadata,
    rank_candidates,
    export_candidates_to_csv,
    get_skills_distribution
)
try:
    from config import Config
    VECTOR_STORE_DIR = Config.VECTOR_STORE_DIR
    METADATA_FILE = Config.METADATA_FILE
except ImportError:
    from dotenv import load_dotenv
    load_dotenv()
    VECTOR_STORE_DIR = os.getenv("VECTOR_STORE_DIR", "./faiss_store")
    METADATA_FILE = os.getenv("METADATA_FILE", "./metadata.pkl")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Page config
st.set_page_config(
    page_title="Resume RAG Chatbot",
    page_icon="📄",
    layout="wide"
)

# Initialize session state
if "vector_store" not in st.session_state:
    st.session_state.vector_store = None
if "metadata_list" not in st.session_state:
    st.session_state.metadata_list = []
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "documents_processed" not in st.session_state:
    st.session_state.documents_processed = False
if "embeddings" not in st.session_state:
    st.session_state.embeddings = None
if "filtered_candidates" not in st.session_state:
    st.session_state.filtered_candidates = []


def initialize_embeddings():
    """Initialize embeddings once and cache in session state."""
    if st.session_state.embeddings is None:
        try:
            st.session_state.embeddings = get_embeddings()
        except ImportError as e:
            # Re-raise with helpful message
            raise ImportError(str(e))
    return st.session_state.embeddings


def process_uploaded_pdfs(uploaded_files: List, use_ocr: bool = False):
    """Process uploaded PDF files and create vector store."""
    if not uploaded_files:
        return
    
    try:
        embeddings = initialize_embeddings()
    except ImportError as e:
        st.error(f"❌ {str(e)}")
        st.info("💡 **Tip:** If you have an OpenAI API key, set it as an environment variable to use OpenAI embeddings instead.")
        return
    documents = []
    metadata_list = []
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    temp_dir = tempfile.mkdtemp()
    
    try:
        for idx, uploaded_file in enumerate(uploaded_files):
            status_text.text(f"Processing {uploaded_file.name}... ({idx + 1}/{len(uploaded_files)})")
            
            # Save uploaded file temporarily
            temp_path = os.path.join(temp_dir, uploaded_file.name)
            with open(temp_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
            
            # Process PDF
            text, metadata = process_resume_pdf(temp_path, use_ocr)
            
            if text.strip():
                # Chunk the text
                chunks = chunk_text(text)
                
                # Create documents with metadata
                for chunk in chunks:
                    doc = Document(
                        page_content=chunk,
                        metadata={
                            "filename": metadata["filename"],
                            "name": metadata["name"],
                            "email": metadata["email"],
                            "phone": metadata["phone"],
                            "skills": ", ".join(metadata["skills"])
                        }
                    )
                    documents.append(doc)
                
                metadata_list.append(metadata)
            
            progress_bar.progress((idx + 1) / len(uploaded_files))
        
        if documents:
            status_text.text("Creating vector store...")
            
            # Create or update vector store
            if st.session_state.vector_store is None:
                st.session_state.vector_store = create_vector_store(
                    documents, embeddings, VECTOR_STORE_DIR
                )
            else:
                # Add new documents to existing store
                st.session_state.vector_store.add_documents(documents)
                st.session_state.vector_store.save_local(VECTOR_STORE_DIR)
            
            # Update metadata
            st.session_state.metadata_list.extend(metadata_list)
            save_metadata(st.session_state.metadata_list, METADATA_FILE)
            
            st.session_state.documents_processed = True
            status_text.text("✅ All resumes processed successfully!")
            
            # Show detailed success message
            total_candidates = len(st.session_state.metadata_list)
            st.success(f"✅ Processed {len(uploaded_files)} resume(s), created {len(documents)} chunks from {total_candidates} candidate(s).")
            logger.info(f"Processed {len(uploaded_files)} resumes: {total_candidates} total candidates, {len(documents)} chunks")
        else:
            st.error("No text could be extracted from the uploaded files.")
    
    finally:
        # Cleanup temp directory
        shutil.rmtree(temp_dir, ignore_errors=True)
        progress_bar.empty()
        status_text.empty()


def load_existing_store():
    """Load existing vector store if available."""
    try:
        embeddings = initialize_embeddings()
        
        if os.path.exists(VECTOR_STORE_DIR) and st.session_state.vector_store is None:
            vector_store = load_vector_store(embeddings, VECTOR_STORE_DIR)
            if vector_store:
                st.session_state.vector_store = vector_store
                st.session_state.documents_processed = True
                
                # Load metadata
                if os.path.exists(METADATA_FILE):
                    loaded_metadata = load_metadata(METADATA_FILE)
                    st.session_state.metadata_list = loaded_metadata
                    logger.info(f"Loaded {len(loaded_metadata)} candidates from metadata file")
    except ImportError as e:
        # Don't fail on startup if embeddings can't be initialized
        # User will see error when they try to upload files
        logger.warning(f"Import error in load_existing_store: {e}")
        pass
    except Exception as e:
        # Other errors - log but don't crash
        logger.error(f"Error loading existing store: {e}")
        pass


# get_llm() is now imported from utils.py


def format_chat_history(chat_history: List[Dict]) -> List:
    """Format chat history for LLM context."""
    messages = []
    for msg in chat_history[-6:]:  # Keep last 6 messages for context
        if msg["role"] == "user":
            messages.append(HumanMessage(content=msg["content"]))
        elif msg["role"] == "assistant":
            messages.append(AIMessage(content=msg["content"]))
    return messages


def generate_response_with_rag(query: str, llm, source_docs: List[Document]) -> str:
    """Generate response using RAG with LLM, ensuring all relevant candidates are mentioned."""
    if not source_docs:
        return "No relevant information found in the resumes."
    
    # Group documents by candidate
    candidates_docs = {}
    for doc in source_docs:
        candidate_name = doc.metadata.get("name", doc.metadata.get("filename", "Unknown"))
        if candidate_name not in candidates_docs:
            candidates_docs[candidate_name] = []
        candidates_docs[candidate_name].append(doc)
    
    # Format context from source documents, organizing by candidate
    context_parts = []
    for candidate_name, docs in candidates_docs.items():
        candidate_info = f"\n[Information from {candidate_name}]"
        if docs[0].metadata.get("email"):
            candidate_info += f"\nEmail: {docs[0].metadata.get('email')}"
        if docs[0].metadata.get("skills"):
            candidate_info += f"\nSkills: {docs[0].metadata.get('skills')}"
        candidate_info += "\n\nRelevant sections:"
        for i, doc in enumerate(docs[:3], 1):  # Max 3 chunks per candidate
            candidate_info += f"\n{i}. {doc.page_content[:400]}..."
        context_parts.append(candidate_info)
    
    context = "\n\n".join(context_parts)
    
    # Get all candidate names for the prompt
    all_candidate_names = list(candidates_docs.keys())
    candidate_list = ", ".join(all_candidate_names) if len(all_candidate_names) <= 5 else f"{len(all_candidate_names)} candidates"
    
    # Format chat history
    history_messages = format_chat_history(st.session_state.chat_history)
    
    # Create system message with explicit instruction to mention all relevant candidates
    system_message = SystemMessage(content="""You are a helpful assistant that searches through resumes to answer questions.

IMPORTANT INSTRUCTIONS:
1. Review ALL candidates mentioned in the context below
2. When answering, mention ALL relevant candidates by name
3. Include specific details from each candidate's resume
4. If multiple candidates match the query, list them all
5. Be comprehensive but concise
6. Always include candidate names when mentioning information from their resumes""")
    
    # Build messages: system + history + current query with context
    prompt = f"""Context from resumes (information from {len(all_candidate_names)} candidate(s): {candidate_list}):

{context}

Question: {query}

Please provide a comprehensive answer mentioning ALL relevant candidates by name with their specific details."""
    
    messages = [system_message] + history_messages + [
        HumanMessage(content=prompt)
    ]
    
    # Generate response
    try:
        response = llm.invoke(messages)
        return response.content
    except Exception as e:
        logger.error(f"LLM error: {e}")
        raise


def query_vector_store(query: str, k: int = 10) -> List[Document]:
    """
    Query vector store and return relevant documents.
    Ensures diversity by getting documents from different candidates.
    """
    if st.session_state.vector_store is None:
        return []
    
    # Get more results than needed to ensure diversity
    results = st.session_state.vector_store.similarity_search_with_score(query, k=k*2)
    
    # Filter to ensure we get documents from different candidates
    unique_candidates = {}
    diverse_results = []
    
    for doc, score in results:
        candidate_id = doc.metadata.get("name", doc.metadata.get("filename", "Unknown"))
        
        # Limit chunks per candidate to ensure diversity
        if candidate_id not in unique_candidates:
            unique_candidates[candidate_id] = []
        
        if len(unique_candidates[candidate_id]) < 3:  # Max 3 chunks per candidate
            unique_candidates[candidate_id].append((doc, score))
            diverse_results.append((doc, score))
        
        if len(diverse_results) >= k:
            break
    
    # Sort by score and return documents
    diverse_results.sort(key=lambda x: x[1], reverse=False)  # Lower score = better match
    return [doc for doc, score in diverse_results[:k]]


def filter_candidates(name_filter: str = "", skill_filter: str = "") -> List[Dict]:
    """Filter candidates by name or skill."""
    candidates = st.session_state.metadata_list.copy()
    
    if name_filter:
        name_lower = name_filter.lower()
        candidates = [c for c in candidates if name_lower in c.get("name", "").lower()]
    
    if skill_filter:
        skill_lower = skill_filter.lower()
        candidates = [
            c for c in candidates
            if any(skill_lower in skill.lower() for skill in c.get("skills", []))
        ]
    
    return candidates


def show_analytics():
    """Display analytics dashboard."""
    if not st.session_state.metadata_list:
        st.info("Upload resumes to see analytics.")
        return
    
    # Show total count prominently
    total_count = len(st.session_state.metadata_list)
    st.subheader(f"📊 Analytics Dashboard - {total_count} Candidate(s)")
    
    # Debug info in expander
    with st.expander("🔍 Debug Info"):
        st.write(f"**Total Candidates in System:** {total_count}")
        st.write(f"**Candidates List:**")
        for idx, candidate in enumerate(st.session_state.metadata_list, 1):
            st.write(f"{idx}. {candidate.get('name', candidate.get('filename', 'Unknown'))} ({candidate.get('filename', 'N/A')})")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Total Candidates", len(st.session_state.metadata_list))
    
    with col2:
        total_skills = sum(len(c.get("skills", [])) for c in st.session_state.metadata_list)
        avg_skills = total_skills / len(st.session_state.metadata_list) if st.session_state.metadata_list else 0
        st.metric("Avg Skills per Candidate", f"{avg_skills:.1f}")
    
    with col3:
        with_emails = sum(1 for c in st.session_state.metadata_list if c.get("email"))
        st.metric("With Email", f"{with_emails}/{len(st.session_state.metadata_list)}")
    
    with col4:
        with_phones = sum(1 for c in st.session_state.metadata_list if c.get("phone"))
        st.metric("With Phone", f"{with_phones}/{len(st.session_state.metadata_list)}")
    
    # Skills distribution chart
    st.subheader("Skills Distribution")
    skills_dist = get_skills_distribution(st.session_state.metadata_list)
    if skills_dist:
        # Get top 15 skills
        top_skills = sorted(skills_dist.items(), key=lambda x: x[1], reverse=True)[:15]
        skills_df = pd.DataFrame(top_skills, columns=["Skill", "Count"])
        
        fig = px.bar(
            skills_df,
            x="Count",
            y="Skill",
            orientation='h',
            title="Top 15 Skills Across All Candidates",
            labels={"Count": "Number of Candidates", "Skill": "Skill Name"}
        )
        fig.update_layout(height=500, yaxis={'categoryorder': 'total ascending'})
        st.plotly_chart(fig, use_container_width=True)
    
    # Candidate completeness
    st.subheader("Candidate Data Completeness")
    completeness_data = []
    
    # Patterns that indicate invalid names
    invalid_name_patterns = [
        r'CERTIFICATE',
        r'RESUME',
        r'CV',
        r'CURRICULUM',
        r'VITAE',
        r'APPLICATION',
        r'PAGE \d+',
        r'^\d+$',  # Just numbers
    ]
    
    for candidate in st.session_state.metadata_list:
        score = 0
        name = candidate.get("name", "").strip()
        
        # Check if name is valid (not empty and not a header)
        is_valid_name = False
        if name:
            name_upper = name.upper()
            is_valid_name = not any(re.search(pattern, name_upper) for pattern in invalid_name_patterns)
            # Also check if it's too short or looks like a filename
            if len(name.split()) < 1 or len(name) < 3:
                is_valid_name = False
        
        if is_valid_name:
            score += 1
        if candidate.get("email"):
            score += 1
        if candidate.get("phone"):
            score += 1
        if candidate.get("skills") and len(candidate.get("skills", [])) > 0:
            score += 1
        
        # Use filename if name is invalid
        display_name = name if is_valid_name else candidate.get("filename", "Unknown")
        completeness_data.append({
            "Candidate": display_name,
            "Completeness Score": score,
            "Max Score": 4
        })
    
    if completeness_data:
        completeness_df = pd.DataFrame(completeness_data)
        completeness_df = completeness_df.sort_values("Completeness Score", ascending=False)
        
        fig = px.bar(
            completeness_df,
            x="Candidate",
            y="Completeness Score",
            title="Candidate Profile Completeness",
            labels={"Candidate": "Candidate Name", "Completeness Score": "Score (out of 4)"}
        )
        fig.update_layout(height=400, xaxis_tickangle=-45)
        st.plotly_chart(fig, use_container_width=True)


# Main UI
st.title("📄 Resume RAG Chatbot")
st.markdown("Upload multiple resume PDFs and query them conversationally!")

# Check for API keys and display status
try:
    from config import Config
    llm_provider = Config.LLM_PROVIDER
    llm_model = Config.LLM_MODEL
except ImportError:
    llm_provider = os.getenv("LLM_PROVIDER", "openai").lower()
    llm_model = os.getenv("LLM_MODEL", "gpt-4o-mini")

llm = get_llm()
if llm:
    # Check if Azure OpenAI is being used
    azure_key = os.getenv("AZURE_OPENAI_KEY")
    if azure_key:
        st.sidebar.success(f"✅ Azure OpenAI LLM enabled - {llm_model}")
    else:
        st.sidebar.success(f"✅ {llm_provider.upper()} LLM enabled - {llm_model}")
    st.sidebar.info("🤖 **Full RAG Mode**: AI will generate intelligent answers")
else:
    st.sidebar.warning("⚠️ **Basic Retrieval Mode** - No LLM provider")
    st.sidebar.error("❌ Only showing raw document snippets (NOT full RAG)")
    
    # Check if Azure credentials exist but aren't working
    azure_key = os.getenv("AZURE_OPENAI_KEY")
    azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    azure_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
    
    if azure_key:
        st.sidebar.info("💡 Azure OpenAI credentials detected - check configuration")
    
    with st.sidebar.expander("🔑 How to Enable Full RAG"):
        st.markdown("""
        **To enable AI-powered responses:**
        
        **Option 1: Azure OpenAI** (if you have credentials)
        ```
        AZURE_OPENAI_KEY=your-key
        AZURE_OPENAI_ENDPOINT=your-endpoint
        AZURE_OPENAI_DEPLOYMENT=your-deployment
        AZURE_OPENAI_API_VERSION=2025-01-01-preview
        ```
        
        **Option 2: Standard OpenAI**
        1. Get API key from [platform.openai.com](https://platform.openai.com/api-keys)
        2. Add to `.env`:
        ```
        OPENAI_API_KEY=sk-your-key-here
        ```
        
        3. Restart the app
        
        **See OPENAI_SETUP.md for detailed instructions**
        
        💡 **Current Mode**: Basic Retrieval (no AI generation)
        """)

# Load existing store on startup
load_existing_store()

# Sidebar
with st.sidebar:
    st.header("📤 Upload Resumes")
    
    uploaded_files = st.file_uploader(
        "Upload PDF resumes",
        type=["pdf"],
        accept_multiple_files=True
    )
    
    use_ocr = st.checkbox("Use OCR (slower, but better for scanned PDFs)")
    
    if st.button("Process Resumes", type="primary"):
        if uploaded_files:
            process_uploaded_pdfs(uploaded_files, use_ocr)
        else:
            st.warning("Please upload at least one PDF file.")
    
    st.divider()
    
    st.header("🔍 Filters")
    
    name_filter = st.text_input("Filter by Name", "")
    skill_filter = st.text_input("Filter by Skill", "")
    
    # Ranking option
    use_ranking = st.checkbox("Rank by relevance", value=False)
    
    if st.button("Apply Filters"):
        filtered = filter_candidates(name_filter, skill_filter)
        
        # Apply ranking if enabled
        if use_ranking and filtered:
            query_text = f"{name_filter} {skill_filter}".strip()
            if query_text:
                ranked_results = rank_candidates(filtered, query_text)
                # Extract just the candidates from ranked tuples
                st.session_state.filtered_candidates = [candidate for candidate, score in ranked_results]
                st.success(f"Found and ranked {len(st.session_state.filtered_candidates)} candidate(s)")
            else:
                st.session_state.filtered_candidates = filtered
        else:
            st.session_state.filtered_candidates = filtered
            st.success(f"Found {len(filtered)} candidate(s)")
    
    st.divider()
    
    st.header("👥 Candidates")
    
    candidates_to_show = st.session_state.get("filtered_candidates", st.session_state.metadata_list)
    
    if candidates_to_show:
        for idx, candidate in enumerate(candidates_to_show):
            with st.expander(f"📄 {candidate.get('name', candidate.get('filename', 'Unknown'))}"):
                st.write(f"**Email:** {candidate.get('email', 'N/A')}")
                st.write(f"**Phone:** {candidate.get('phone', 'N/A')}")
                st.write(f"**Skills:** {', '.join(candidate.get('skills', []))}")
                st.write(f"**File:** {candidate.get('filename', 'N/A')}")
    else:
        st.info("No candidates loaded. Upload resumes to get started.")
    
    st.divider()
    
    st.header("📤 Export")
    
    candidates_to_export = st.session_state.get("filtered_candidates", st.session_state.metadata_list)
    if candidates_to_export:
        if st.button("📥 Export to CSV"):
            try:
                export_path = "candidates_export.csv"
                if export_candidates_to_csv(candidates_to_export, export_path):
                    with open(export_path, 'rb') as f:
                        st.download_button(
                            label="Download CSV",
                            data=f,
                            file_name="candidates_export.csv",
                            mime="text/csv"
                        )
                    st.success(f"Exported {len(candidates_to_export)} candidates to CSV")
                else:
                    st.error("Failed to export candidates")
            except Exception as e:
                st.error(f"Export error: {e}")
                logger.error(f"Export error: {e}")
    
    st.divider()
    
    if st.button("🗑️ Clear All Data", type="secondary"):
        if os.path.exists(VECTOR_STORE_DIR):
            shutil.rmtree(VECTOR_STORE_DIR)
        if os.path.exists(METADATA_FILE):
            os.remove(METADATA_FILE)
        st.session_state.vector_store = None
        st.session_state.metadata_list = []
        st.session_state.chat_history = []
        st.session_state.documents_processed = False
        st.session_state.filtered_candidates = []
        st.rerun()

# Main chat area
if st.session_state.documents_processed and st.session_state.vector_store:
    # Add tabs for Chat and Analytics
    tab1, tab2 = st.tabs(["💬 Chat", "📊 Analytics"])
    
    with tab1:
        st.header("💬 Chat with Resumes")
        
        # Display chat history
        for message in st.session_state.chat_history:
            with st.chat_message(message["role"]):
                st.write(message["content"])
                if "sources" in message:
                    with st.expander("📎 Source Documents"):
                        for source in message["sources"]:
                            st.write(f"**From:** {source.metadata.get('name', source.metadata.get('filename', 'Unknown'))}")
                            st.write(f"**Snippet:** {source.page_content[:200]}...")
        
        # Chat input
        query = st.chat_input("Ask a question about the resumes...")
    
        if query:
            # Add user message to chat
            st.session_state.chat_history.append({"role": "user", "content": query})
            with st.chat_message("user"):
                st.write(query)
            
            # Get response
            with st.chat_message("assistant"):
                with st.spinner("Searching resumes..."):
                    # Retrieve relevant documents (increased k for better diversity)
                    source_docs = query_vector_store(query, k=10)
                    
                    # Get LLM if available (use cached or get new)
                    if "llm_instance" not in st.session_state or st.session_state.llm_instance is None:
                        st.session_state.llm_instance = get_llm()
                    llm = st.session_state.llm_instance
                    
                    if llm and source_docs:
                        # Use LLM with RAG
                        try:
                            answer = generate_response_with_rag(query, llm, source_docs)
                        except Exception as e:
                            st.error(f"Error: {e}")
                            logger.error(f"RAG generation error: {e}")
                            # Fallback to basic retrieval - show all candidates
                            candidates_found = {}
                            for doc in source_docs:
                                candidate_name = doc.metadata.get("name", doc.metadata.get("filename", "Unknown"))
                                if candidate_name not in candidates_found:
                                    candidates_found[candidate_name] = []
                                candidates_found[candidate_name].append(doc)
                            
                            answer = f"Found relevant information from {len(candidates_found)} candidate(s):\n\n"
                            for idx, (candidate_name, docs) in enumerate(candidates_found.items(), 1):
                                answer += f"**{idx}. {candidate_name}**\n"
                                if docs[0].metadata.get("email"):
                                    answer += f"Email: {docs[0].metadata.get('email')}\n"
                                answer += f"Relevant sections:\n"
                                for i, doc in enumerate(docs[:3], 1):
                                    answer += f"  {i}. {doc.page_content[:300]}...\n\n"
                    elif source_docs:
                        # Basic retrieval without LLM - show all candidates
                        candidates_found = {}
                        for doc in source_docs:
                            candidate_name = doc.metadata.get("name", doc.metadata.get("filename", "Unknown"))
                            if candidate_name not in candidates_found:
                                candidates_found[candidate_name] = []
                            candidates_found[candidate_name].append(doc)
                        
                        answer = f"Found relevant information from {len(candidates_found)} candidate(s):\n\n"
                        for idx, (candidate_name, docs) in enumerate(candidates_found.items(), 1):
                            answer += f"**{idx}. {candidate_name}**\n"
                            if docs[0].metadata.get("email"):
                                answer += f"Email: {docs[0].metadata.get('email')}\n"
                            answer += f"Relevant sections:\n"
                            for i, doc in enumerate(docs[:3], 1):
                                answer += f"  {i}. {doc.page_content[:300]}...\n\n"
                    else:
                        answer = "No relevant information found in the resumes."
                    
                    st.write(answer)
                    
                    # Show source documents
                    if source_docs:
                        with st.expander("📎 Source Documents"):
                            for doc in source_docs[:5]:
                                st.markdown(f"**Candidate:** {doc.metadata.get('name', doc.metadata.get('filename', 'Unknown'))}")
                                st.markdown(f"**Email:** {doc.metadata.get('email', 'N/A')}")
                                st.markdown(f"**Skills:** {doc.metadata.get('skills', 'N/A')}")
                                st.markdown(f"**Snippet:** {doc.page_content[:300]}...")
                                st.divider()
                    
                    # Add assistant response to chat history
                    st.session_state.chat_history.append({
                        "role": "assistant",
                        "content": answer,
                        "sources": source_docs
                    })
        
        # Clear chat button
        if st.button("Clear Chat History"):
            st.session_state.chat_history = []
            st.rerun()
    
    with tab2:
        show_analytics()

else:
    st.info("👈 Please upload and process resume PDFs in the sidebar to start chatting!")
    
    if st.session_state.metadata_list:
        st.write(f"**Loaded:** {len(st.session_state.metadata_list)} candidate(s)")
        
        # Show analytics even without processed documents
        st.divider()
        show_analytics()
    else:
        st.write("**Status:** No resumes loaded yet")
        
        # Show features/instructions
        st.divider()
        st.subheader("🚀 Getting Started")
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("""
            **Features:**
            - 📄 Multi-PDF processing
            - 🔍 Semantic search with FAISS
            - 🤖 AI-powered querying
            - 📊 Analytics dashboard
            - 📥 CSV export
            - 🎯 Advanced filtering
            """)
        with col2:
            st.markdown("""
            **How to Use:**
            1. Upload resume PDFs in sidebar
            2. Click "Process Resumes"
            3. Start chatting with your resumes
            4. Use filters to find specific candidates
            5. Export results to CSV
            """)


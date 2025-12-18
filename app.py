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
                            "skills": ", ".join(metadata["skills"]),
                            "years_experience": metadata.get("years_experience", 0),
                            "education_level": metadata.get("education_level", ""),
                            "job_titles": ", ".join(metadata.get("job_titles", [])),
                            "companies": ", ".join(metadata.get("companies", [])),
                            "location": metadata.get("location", ""),
                            "certifications": ", ".join(metadata.get("certifications", []))
                        }
                    )
                    documents.append(doc)
                
                metadata_list.append(metadata)
            
            progress_bar.progress((idx + 1) / len(uploaded_files))
        
        if documents:
            status_text.text("Creating vector store...")
            
            # Check if persistence is enabled (disabled by default for multi-user)
            enable_persistence = os.getenv("ENABLE_PERSISTENCE", "false").lower() == "true"
            
            # Create or update vector store
            if st.session_state.vector_store is None:
                # Only save to disk if persistence is enabled
                persist_dir = VECTOR_STORE_DIR if enable_persistence else None
                st.session_state.vector_store = create_vector_store(
                    documents, embeddings, persist_dir
                )
            else:
                # Add new documents to existing store
                st.session_state.vector_store.add_documents(documents)
                # Only save to disk if persistence is enabled
                if enable_persistence:
                    st.session_state.vector_store.save_local(VECTOR_STORE_DIR)
            
            # Update metadata (session state only)
            st.session_state.metadata_list.extend(metadata_list)
            
            # Only save to disk if persistence is enabled
            if enable_persistence:
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
    """Load existing vector store if available (only if persistence is enabled)."""
    # Check if persistence is enabled (disabled by default for multi-user deployments)
    enable_persistence = os.getenv("ENABLE_PERSISTENCE", "false").lower() == "true"
    
    # On Streamlit Cloud or multi-user deployments, disable persistence by default
    if not enable_persistence:
        # Clear any existing persistent data to prevent cross-user data leakage
        if os.path.exists(VECTOR_STORE_DIR):
            try:
                shutil.rmtree(VECTOR_STORE_DIR)
                logger.info("Cleared persistent vector store (persistence disabled)")
            except Exception as e:
                logger.warning(f"Could not clear vector store: {e}")
        
        if os.path.exists(METADATA_FILE):
            try:
                os.remove(METADATA_FILE)
                logger.info("Cleared persistent metadata (persistence disabled)")
            except Exception as e:
                logger.warning(f"Could not clear metadata: {e}")
        
        return  # Don't load persistent data
    
    # Only load if persistence is explicitly enabled
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
        logger.warning(f"Import error in load_existing_store: {e}")
        pass
    except Exception as e:
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
    """Display enhanced analytics dashboard with detailed insights."""
    if not st.session_state.metadata_list:
        st.info("📤 Upload resumes to see analytics.")
        return
    
    total_count = len(st.session_state.metadata_list)
    
    # Header with summary
    st.markdown("## 📊 Analytics Dashboard")
    st.markdown(f"**Total Candidates Analyzed:** {total_count}")
    st.divider()
    
    # Key Metrics - Enhanced with more details and mobile responsive
    st.markdown("### 📈 Key Metrics")
    
    # Responsive columns: 5 on desktop, 2 on tablet, 1 on mobile
    col1, col2, col3, col4, col5 = st.columns([1, 1, 1, 1, 1])
    
    with col1:
        st.metric(
            label="👥 Total Candidates",
            value=total_count,
            help="Total number of resumes processed"
        )
    
    with col2:
        total_skills = sum(len(c.get("skills", [])) for c in st.session_state.metadata_list)
        avg_skills = total_skills / total_count if total_count > 0 else 0
        st.metric(
            label="🛠️ Avg Skills",
            value=f"{avg_skills:.1f}",
            help="Average number of skills per candidate"
        )
    
    with col3:
        with_emails = sum(1 for c in st.session_state.metadata_list if c.get("email"))
        email_pct = (with_emails / total_count * 100) if total_count > 0 else 0
        st.metric(
            label="📧 With Email",
            value=f"{with_emails}/{total_count}",
            delta=f"{email_pct:.0f}%",
            delta_color="normal",
            help="Candidates with email addresses"
        )
    
    with col4:
        with_phones = sum(1 for c in st.session_state.metadata_list if c.get("phone"))
        phone_pct = (with_phones / total_count * 100) if total_count > 0 else 0
        st.metric(
            label="📞 With Phone",
            value=f"{with_phones}/{total_count}",
            delta=f"{phone_pct:.0f}%",
            delta_color="normal",
            help="Candidates with phone numbers"
        )
    
    with col5:
        total_unique_skills = len(get_skills_distribution(st.session_state.metadata_list))
        st.metric(
            label="🎯 Unique Skills",
            value=total_unique_skills,
            help="Total number of unique skills found"
        )
    
    st.divider()
    
    # Skills Analysis Section - Mobile Responsive
    st.markdown("### 🛠️ Skills Analysis")
    skills_dist = get_skills_distribution(st.session_state.metadata_list)
    
    if skills_dist:
        # Responsive columns: stack on mobile
        col1, col2 = st.columns([2, 1])
        
        with col1:
            # Top Skills Bar Chart
            top_skills = sorted(skills_dist.items(), key=lambda x: x[1], reverse=True)[:20]
            skills_df = pd.DataFrame(top_skills, columns=["Skill", "Count"])
            
            # Calculate percentage
            skills_df["Percentage"] = (skills_df["Count"] / total_count * 100).round(1)
            
            fig = px.bar(
                skills_df,
                x="Count",
                y="Skill",
                orientation='h',
                title="Top 20 Skills Distribution",
                labels={"Count": "Number of Candidates", "Skill": "Skill Name"},
                color="Count",
                color_continuous_scale="Blues",
                text="Count"
            )
            fig.update_traces(textposition='outside')
            fig.update_layout(
                height=600,
                yaxis={'categoryorder': 'total ascending'},
                xaxis_title="Number of Candidates",
                yaxis_title="",
                showlegend=False,
                autosize=True
            )
            # Mobile responsive chart
            st.plotly_chart(fig, width='stretch', config={'displayModeBar': True, 'responsive': True})
        
        with col2:
            st.markdown("#### 📋 Top Skills List")
            for idx, (skill, count) in enumerate(top_skills[:10], 1):
                percentage = (count / total_count * 100)
                st.markdown(f"""
                **{idx}. {skill}**
                - {count} candidate(s) ({percentage:.1f}%)
                """)
            
            if len(top_skills) > 10:
                with st.expander(f"View all {len(top_skills)} skills"):
                    for idx, (skill, count) in enumerate(top_skills[10:], 11):
                        percentage = (count / total_count * 100)
                        st.markdown(f"**{idx}. {skill}** - {count} ({percentage:.1f}%)")
    
    st.divider()
    
    # Candidate Completeness Section
    st.markdown("### ✅ Candidate Profile Completeness")
    
    # Patterns that indicate invalid names
    invalid_name_patterns = [
        r'CERTIFICATE', r'RESUME', r'CV', r'CURRICULUM', r'VITAE',
        r'APPLICATION', r'PAGE \d+', r'^\d+$',
    ]
    
    completeness_data = []
    completeness_details = []
    
    for candidate in st.session_state.metadata_list:
        score = 0
        details = {"name": False, "email": False, "phone": False, "skills": False}
        name = candidate.get("name", "").strip()
        
        # Check if name is valid
        is_valid_name = False
        if name:
            name_upper = name.upper()
            is_valid_name = not any(re.search(pattern, name_upper) for pattern in invalid_name_patterns)
            if len(name.split()) < 1 or len(name) < 3:
                is_valid_name = False
        
        if is_valid_name:
            score += 1
            details["name"] = True
        if candidate.get("email"):
            score += 1
            details["email"] = True
        if candidate.get("phone"):
            score += 1
            details["phone"] = True
        if candidate.get("skills") and len(candidate.get("skills", [])) > 0:
            score += 1
            details["skills"] = True
        
        display_name = name if is_valid_name else candidate.get("filename", "Unknown")
        completeness_data.append({
            "Candidate": display_name,
            "Completeness Score": score,
            "Max Score": 4,
            "Percentage": (score / 4 * 100)
        })
        completeness_details.append({
            "Candidate": display_name,
            **details
        })
    
    # Initialize variables for summary stats
    completeness_df = None
    avg_completeness = 0
    perfect_profiles = 0
    
    if completeness_data:
        completeness_df = pd.DataFrame(completeness_data)
        completeness_df = completeness_df.sort_values("Completeness Score", ascending=False)
        avg_completeness = completeness_df["Completeness Score"].mean()
        perfect_profiles = len(completeness_df[completeness_df["Completeness Score"] == 4])
        
        # Responsive columns
        col1, col2 = st.columns([2, 1])
        
        with col1:
            # Enhanced completeness chart - mobile responsive
            fig = px.bar(
                completeness_df,
                x="Candidate",
                y="Completeness Score",
                title="Candidate Profile Completeness Score",
                labels={"Candidate": "Candidate Name", "Completeness Score": "Score (out of 4)"},
                color="Completeness Score",
                color_continuous_scale=["#ff4444", "#ffaa00", "#ffdd00", "#88ff00", "#00ff00"],
                text="Completeness Score"
            )
            fig.update_traces(textposition='outside')
            fig.update_layout(
                height=500,
                xaxis_tickangle=-45,
                xaxis_title="",
                yaxis_title="Completeness Score (out of 4)",
                showlegend=False,
                autosize=True
            )
            st.plotly_chart(fig, width='stretch', config={'displayModeBar': True, 'responsive': True})
        
        with col2:
            st.markdown("#### 📊 Completeness Stats")
            st.metric("Average Score", f"{avg_completeness:.2f}/4.0")
            st.metric("Complete Profiles", f"{perfect_profiles}/{total_count}")
            
            incomplete = len(completeness_df[completeness_df["Completeness Score"] < 4])
            st.metric("Incomplete Profiles", f"{incomplete}/{total_count}")
            
            st.divider()
            st.markdown("#### 📋 Details")
            with st.expander("View Completeness Details"):
                details_df = pd.DataFrame(completeness_details)
                st.dataframe(details_df, width='stretch', hide_index=True)
    
    st.divider()
    
    # Skills Categories Analysis
    st.markdown("### 🎯 Skills Categories")
    
    # Categorize skills
    skill_categories = {
        "Programming Languages": ["Python", "JavaScript", "Java", "C++", "C#", "TypeScript", "Go", "Rust", "Swift", "Kotlin", "PHP", "Ruby"],
        "Web Frameworks": ["React", "Angular", "Vue", "Django", "Flask", "Node.js", "Spring", ".NET"],
        "Databases": ["SQL", "MongoDB", "PostgreSQL", "MySQL"],
        "Cloud & DevOps": ["AWS", "Docker", "Kubernetes", "Linux", "Git"],
        "Machine Learning": ["Machine Learning", "Deep Learning", "TensorFlow", "PyTorch"],
        "Frontend": ["HTML", "CSS"],
        "Other": []
    }
    
    categorized_skills = {cat: [] for cat in skill_categories.keys()}
    
    for skill, count in skills_dist.items():
        categorized = False
        for category, keywords in skill_categories.items():
            if any(keyword.lower() in skill.lower() for keyword in keywords):
                categorized_skills[category].append((skill, count))
                categorized = True
                break
        if not categorized:
            categorized_skills["Other"].append((skill, count))
    
    # Create pie chart for skill categories
    category_counts = {cat: len(skills) for cat, skills in categorized_skills.items() if skills}
    
    if category_counts:
        # Responsive columns: stack on mobile
        col1, col2 = st.columns([1, 1])
        
        with col1:
            fig_pie = px.pie(
                values=list(category_counts.values()),
                names=list(category_counts.keys()),
                title="Skills by Category Distribution",
                hole=0.4
            )
            fig_pie.update_traces(textposition='inside', textinfo='percent+label')
            fig_pie.update_layout(height=400, autosize=True)
            st.plotly_chart(fig_pie, width='stretch', config={'displayModeBar': True, 'responsive': True})
        
        with col2:
            st.markdown("#### 📊 Category Breakdown")
            for category, skills_list in categorized_skills.items():
                if skills_list:
                    total_in_category = sum(count for _, count in skills_list)
                    st.markdown(f"""
                    **{category}**
                    - {len(skills_list)} unique skill(s)
                    - {total_in_category} total mentions
                    """)
    
    st.divider()
    
    # ========== RECRUITMENT-FOCUSED ANALYTICS ==========
    st.markdown("## 🏢 Recruitment Analytics (ATS-Style)")
    st.markdown("**Professional metrics used by HR departments and recruiters**")
    st.divider()
    
    # Experience Level Distribution
    st.markdown("### 📊 Experience Level Distribution")
    experience_data = []
    for candidate in st.session_state.metadata_list:
        years = candidate.get("years_experience", 0)
        if years > 0:
            experience_data.append(years)
    
    if experience_data:
        col1, col2 = st.columns([2, 1])
        
        with col1:
            # Experience histogram
            exp_df = pd.DataFrame({"Years of Experience": experience_data})
            fig = px.histogram(
                exp_df,
                x="Years of Experience",
                nbins=10,
                title="Years of Experience Distribution",
                labels={"Years of Experience": "Years", "count": "Number of Candidates"},
                color_discrete_sequence=['#1f77b4']
            )
            fig.update_layout(height=400, showlegend=False, autosize=True)
            st.plotly_chart(fig, width='stretch', config={'displayModeBar': True, 'responsive': True})
        
        with col2:
            st.markdown("#### 📈 Experience Stats")
            avg_exp = sum(experience_data) / len(experience_data) if experience_data else 0
            st.metric("Average Experience", f"{avg_exp:.1f} years")
            
            # Show calculation breakdown
            with st.expander("🔍 Calculation Details", expanded=False):
                st.markdown("**Individual Experience Values:**")
                for i, years in enumerate(experience_data, 1):
                    st.markdown(f"- Candidate {i}: **{years} years**")
                st.markdown(f"\n**Calculation:** ({' + '.join(map(str, experience_data))}) ÷ {len(experience_data)} = **{avg_exp:.2f} years**")
                st.caption(f"Displayed as: {avg_exp:.1f} years (rounded to 1 decimal)")
            
            # Categorize experience levels
            entry_level = sum(1 for y in experience_data if 0 < y <= 2)
            mid_level = sum(1 for y in experience_data if 2 < y <= 5)
            senior_level = sum(1 for y in experience_data if 5 < y <= 10)
            expert_level = sum(1 for y in experience_data if y > 10)
            
            st.markdown(f"""
            **Experience Levels:**
            - 🟢 Entry (0-2 yrs): {entry_level}
            - 🟡 Mid (3-5 yrs): {mid_level}
            - 🟠 Senior (6-10 yrs): {senior_level}
            - 🔴 Expert (10+ yrs): {expert_level}
            """)
            
            # Explanation of how experience is calculated
            with st.expander("ℹ️ How Experience Is Calculated", expanded=False):
                st.markdown("""
                **Experience Calculation Process:**
                
                1. **Date Detection:** System searches for date ranges in resume (e.g., "2015 - 2020", "Jan 2018 - Present")
                
                2. **Work Experience Only:** System filters out education dates by checking context:
                   - ✅ **Includes:** Dates near work keywords (experience, employment, job titles, companies)
                   - ❌ **Excludes:** Dates near education keywords (university, college, degree, graduation)
                
                3. **Years Calculation:** For each work position:
                   - Past positions: End Year - Start Year
                   - Current positions: Current Year - Start Year
                
                4. **Sum Total:** All years from multiple work positions are summed
                
                5. **Categorization:**
                   - Entry: 0-2 years
                   - Mid: 3-5 years
                   - Senior: 6-10 years
                   - Expert: 10+ years
                
                **Example:** Resume with work positions from 2015-2018 (3 yrs) and 2018-2024 (6 yrs) = **9 years total** (Senior level)
                
                ⚠️ **Note:** Education/school years are NOT counted as work experience.
                
                See `EXPERIENCE_CALCULATION.md` for detailed documentation.
                """)
    else:
        # Show message when no experience data is found
        st.info("""
        📋 **No work experience data found**
        
        This could happen if:
        - Resumes don't have work experience dates in standard formats (e.g., "2015 - 2020")
        - Dates are only in education sections (which are excluded)
        - Date formats are not recognized (try formats like "Jan 2018 - Present" or "2015-2020")
        
        **Tip:** Make sure resumes include work experience sections with date ranges.
        """)
    
    st.divider()
    
    # Education Level Breakdown
    st.markdown("### 🎓 Education Level Breakdown")
    education_data = {}
    for candidate in st.session_state.metadata_list:
        edu = candidate.get("education_level", "")
        # Normalize empty strings and handle "Not Specified"
        if not edu or edu.strip() == "":
            edu = "Not Specified"
        education_data[edu] = education_data.get(edu, 0) + 1
    
    if education_data:
        col1, col2 = st.columns([1, 1])
        
        with col1:
            # Sort education levels by standard order, then by count
            education_order = ["PhD", "Master's", "Bachelor's", "Associate's", "Diploma", "Not Specified"]
            sorted_data = sorted(
                education_data.items(),
                key=lambda x: (education_order.index(x[0]) if x[0] in education_order else 999, -x[1])
            )
            
            edu_df = pd.DataFrame(sorted_data, columns=["Education Level", "Count"])
            
            # Use colors that work well with dark theme
            colors = px.colors.qualitative.Set3[:len(education_data)]
            
            fig = px.pie(
                edu_df,
                values="Count",
                names="Education Level",
                title="Education Distribution",
                hole=0.4,
                color_discrete_sequence=colors
            )
            fig.update_traces(
                textposition='inside', 
                textinfo='percent+label',
                hovertemplate='<b>%{label}</b><br>Count: %{value}<br>Percentage: %{percent}<extra></extra>'
            )
            fig.update_layout(
                height=400, 
                autosize=True,
                font=dict(color='#fafafa'),
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                title_font=dict(color='#4fc3f7', size=16)
            )
            st.plotly_chart(fig, width='stretch', config={'displayModeBar': True, 'responsive': True})
        
        with col2:
            st.markdown("#### 📚 Education Details")
            
            # Show sorted list with better formatting
            total_with_education = sum(count for level, count in education_data.items() if level != "Not Specified")
            total_without_education = education_data.get("Not Specified", 0)
            
            # Show education levels first (in order)
            for edu_level, count in sorted_data:
                if edu_level != "Not Specified":
                    percentage = (count / total_count * 100)
                    st.markdown(f"**{edu_level}**: {count} candidate{'s' if count != 1 else ''} ({percentage:.1f}%)")
            
            # Show "Not Specified" separately if present
            if total_without_education > 0:
                percentage = (total_without_education / total_count * 100)
                st.markdown("---")
                st.markdown(f"**Not Specified**: {total_without_education} candidate{'s' if total_without_education != 1 else ''} ({percentage:.1f}%)")
                st.caption("💡 Education level could not be detected from resume text")
            
            # Summary
            if total_with_education > 0:
                st.markdown("---")
                coverage_pct = (total_with_education / total_count * 100)
                st.markdown(f"**📊 Coverage**: {total_with_education}/{total_count} candidates ({coverage_pct:.1f}%)")
    
    else:
        st.info("📋 No education data available")
    
    st.divider()
    
    # Job Title Distribution
    st.markdown("### 💼 Job Title Distribution")
    all_titles = []
    for candidate in st.session_state.metadata_list:
        titles = candidate.get("job_titles", [])
        all_titles.extend(titles)
    
    if all_titles:
        # Count full titles, not just first word
        title_counts = {}
        for title in all_titles:
            title_normalized = title.strip()
            if len(title_normalized) > 0:
                title_counts[title_normalized] = title_counts.get(title_normalized, 0) + 1
        
        top_titles = sorted(title_counts.items(), key=lambda x: x[1], reverse=True)[:15]
        
        col1, col2 = st.columns([2, 1])
        
        with col1:
            titles_df = pd.DataFrame(top_titles, columns=["Job Title", "Count"])
            fig = px.bar(
                titles_df,
                x="Count",
                y="Job Title",
                orientation='h',
                title="Top 15 Job Titles",
                labels={"Count": "Number of Candidates", "Job Title": ""},
                color="Count",
                color_continuous_scale="Viridis"
            )
            fig.update_layout(
                height=500,
                yaxis={'categoryorder': 'total ascending'},
                showlegend=False,
                autosize=True
            )
            st.plotly_chart(fig, width='stretch', config={'displayModeBar': True, 'responsive': True})
        
        with col2:
            st.markdown("#### 💼 Top Titles")
            for idx, (title, count) in enumerate(top_titles[:10], 1):
                percentage = (count / total_count * 100)
                st.markdown(f"**{idx}. {title}**")
                st.markdown(f"   - {count} candidate{'s' if count != 1 else ''} ({percentage:.1f}%)")
    else:
        st.info("📋 **No job titles found**\n\nNo job titles were detected in the uploaded resumes. Titles are extracted from experience sections.")
    
    st.divider()
    
    # Top Companies
    st.markdown("### 🏛️ Previous Companies")
    all_companies = []
    for candidate in st.session_state.metadata_list:
        companies = candidate.get("companies", [])
        all_companies.extend(companies)
    
    if all_companies:
        company_counts = {}
        for company in all_companies:
            company_counts[company] = company_counts.get(company, 0) + 1
        
        top_companies = sorted(company_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        
        col1, col2 = st.columns([1, 1])
        
        with col1:
            companies_df = pd.DataFrame(top_companies, columns=["Company", "Count"])
            fig = px.bar(
                companies_df,
                x="Company",
                y="Count",
                title="Top Companies (Previous Employers)",
                labels={"Count": "Number of Candidates", "Company": "Company Name"},
                color="Count",
                color_continuous_scale="Blues"
            )
            fig.update_layout(height=400, xaxis_tickangle=-45, showlegend=False, autosize=True)
            st.plotly_chart(fig, width='stretch', config={'displayModeBar': True, 'responsive': True})
        
        with col2:
            st.markdown("#### 🏢 Company List")
            for idx, (company, count) in enumerate(top_companies, 1):
                percentage = (count / total_count * 100)
                st.markdown(f"**{idx}. {company}**")
                st.markdown(f"   - {count} candidate(s) ({percentage:.1f}%)")
    else:
        st.info("📋 **No companies found**\n\nNo company names were detected in the uploaded resumes. Companies are extracted from experience sections.")
    
    st.divider()
    
    # Certifications
    st.markdown("### 🏆 Certifications & Credentials")
    all_certs = []
    for candidate in st.session_state.metadata_list:
        certs = candidate.get("certifications", [])
        all_certs.extend(certs)
    
    if all_certs:
        cert_counts = {}
        for cert in all_certs:
            cert_counts[cert] = cert_counts.get(cert, 0) + 1
        
        top_certs = sorted(cert_counts.items(), key=lambda x: x[1], reverse=True)
        
        col1, col2 = st.columns([2, 1])
        
        with col1:
            certs_df = pd.DataFrame(top_certs, columns=["Certification", "Count"])
            fig = px.bar(
                certs_df,
                x="Certification",
                y="Count",
                title="Certifications Distribution",
                labels={"Count": "Number of Candidates", "Certification": "Certification Name"},
                color="Count",
                color_continuous_scale="Greens"
            )
            fig.update_layout(height=400, xaxis_tickangle=-45, showlegend=False, autosize=True)
            st.plotly_chart(fig, width='stretch', config={'displayModeBar': True, 'responsive': True})
        
        with col2:
            st.markdown("#### 🎖️ Top Certifications")
            for idx, (cert, count) in enumerate(top_certs[:10], 1):
                percentage = (count / total_count * 100)
                st.markdown(f"**{idx}. {cert}**")
                st.markdown(f"   - {count} ({percentage:.1f}%)")
    else:
        st.info("📋 **No certifications found**\n\nNo certifications were detected in the uploaded resumes.")
    
    st.divider()
    
    # Candidate Ranking/Scoring System
    st.markdown("### ⭐ Candidate Ranking & Fit Score")
    st.markdown("**ATS-style scoring based on profile completeness and experience**")
    
    # Explanation of scoring system
    with st.expander("ℹ️ How Fit Scores Are Calculated", expanded=False):
        st.markdown("""
        **Fit Score Calculation (0-100 points):**
        
        - **Name (10 pts):** Valid name found = 10 points
        - **Contact Info (20 pts):** Email (10) + Phone (10)
        - **Skills (20 pts):** 2 points per skill, max 20 (10+ skills)
        - **Experience (25 pts):** 2.5 points per year, max 25 (10+ years)
        - **Education (15 pts):** Education level found = 15 points
        - **Certifications (10 pts):** 2 points per cert, max 10 (5+ certs)
        
        **Example:** Candidate with valid name, email, phone, 8 skills, 5 years exp, Bachelor's, 2 certs
        = 10 + 10 + 10 + 16 + 12.5 + 15 + 4 = **77.5/100**
        
        See `SCORING_EXPLANATION.md` for detailed documentation.
        """)
    
    ranked_candidates = []
    for candidate in st.session_state.metadata_list:
        score = 0
        details = {}
        
        # Name (10 points)
        name = candidate.get("name", "").strip()
        is_valid_name = False
        if name:
            name_upper = name.upper()
            invalid_patterns = [r'CERTIFICATE', r'RESUME', r'CV', r'CURRICULUM', r'VITAE']
            is_valid_name = not any(re.search(pattern, name_upper) for pattern in invalid_patterns)
            if len(name.split()) < 1 or len(name) < 3:
                is_valid_name = False
        
        if is_valid_name:
            score += 10
            details["name"] = "✓"
        else:
            details["name"] = "✗"
        
        # Contact info (20 points)
        if candidate.get("email"):
            score += 10
            details["email"] = "✓"
        else:
            details["email"] = "✗"
        
        if candidate.get("phone"):
            score += 10
            details["phone"] = "✓"
        else:
            details["phone"] = "✗"
        
        # Skills (20 points)
        skills_count = len(candidate.get("skills", []))
        if skills_count > 0:
            score += min(20, skills_count * 2)  # 2 points per skill, max 20
            details["skills"] = f"{skills_count} skills"
        else:
            details["skills"] = "0 skills"
        
        # Experience (25 points)
        years_exp = candidate.get("years_experience", 0)
        if years_exp > 0:
            score += min(25, years_exp * 2.5)  # 2.5 points per year, max 25
            details["experience"] = f"{years_exp} years"
        else:
            details["experience"] = "N/A"
        
        # Education (15 points)
        if candidate.get("education_level"):
            score += 15
            details["education"] = candidate.get("education_level")
        else:
            details["education"] = "N/A"
        
        # Certifications (10 points)
        certs_count = len(candidate.get("certifications", []))
        if certs_count > 0:
            score += min(10, certs_count * 2)  # 2 points per cert, max 10
            details["certifications"] = f"{certs_count} certs"
        else:
            details["certifications"] = "0 certs"
        
        display_name = name if is_valid_name else candidate.get("filename", "Unknown")
        ranked_candidates.append({
            "Candidate": display_name,
            "Fit Score": round(score, 1),
            "Max Score": 100,
            "Experience": details["experience"],
            "Education": details["education"],
            "Skills": details["skills"],
            "Certs": details["certifications"],
            "Contact": f"{details['email']} {details['phone']}"
        })
    
    if ranked_candidates:
        ranked_df = pd.DataFrame(ranked_candidates)
        ranked_df = ranked_df.sort_values("Fit Score", ascending=False)
        
        col1, col2 = st.columns([2, 1])
        
        with col1:
            fig = px.bar(
                ranked_df,
                x="Candidate",
                y="Fit Score",
                title="Candidate Fit Score Ranking (0-100)",
                labels={"Candidate": "Candidate Name", "Fit Score": "Fit Score"},
                color="Fit Score",
                color_continuous_scale=["#ff4444", "#ffaa00", "#88ff00", "#00ff00"],
                text="Fit Score"
            )
            fig.update_traces(textposition='outside')
            fig.update_layout(
                height=500,
                xaxis_tickangle=-45,
                yaxis_range=[0, 100],
                showlegend=False,
                autosize=True
            )
            st.plotly_chart(fig, width='stretch', config={'displayModeBar': True, 'responsive': True})
        
        with col2:
            st.markdown("#### 🏆 Top Candidates")
            for rank, (idx, row) in enumerate(ranked_df.head(10).iterrows(), 1):
                st.markdown(f"""
                **#{rank} {row['Candidate']}**
                - Score: **{row['Fit Score']}/100**
                - Exp: {row['Experience']}
                - Edu: {row['Education']}
                """)
            
            st.divider()
            avg_score = ranked_df["Fit Score"].mean()
            st.metric("Average Fit Score", f"{avg_score:.1f}/100")
            
            top_25_pct = len(ranked_df[ranked_df["Fit Score"] >= 75])
            st.metric("High Fit (75+)", f"{top_25_pct}/{total_count}")
        
        # Detailed ranking table
        st.markdown("#### 📋 Detailed Ranking Table")
        st.dataframe(
            ranked_df[["Candidate", "Fit Score", "Experience", "Education", "Skills", "Certs", "Contact"]],
            width='stretch',
            hide_index=True,
            height=400
        )
    
    st.divider()
    
    # Location Distribution (if available)
    locations = [c.get("location", "") for c in st.session_state.metadata_list if c.get("location")]
    if locations:
        st.markdown("### 📍 Location Distribution")
        location_counts = {}
        for loc in locations:
            location_counts[loc] = location_counts.get(loc, 0) + 1
        
        top_locations = sorted(location_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        loc_df = pd.DataFrame(top_locations, columns=["Location", "Count"])
        
        fig = px.bar(
            loc_df,
            x="Location",
            y="Count",
            title="Top Candidate Locations",
            labels={"Count": "Number of Candidates", "Location": "City, State"},
            color="Count",
            color_continuous_scale="Purples"
        )
        fig.update_layout(height=400, xaxis_tickangle=-45, showlegend=False, autosize=True)
        st.plotly_chart(fig, width='stretch', config={'displayModeBar': True, 'responsive': True})
    
    st.divider()
    
    # Candidate Details Table
    st.markdown("### 👥 Candidate Details")
    
    # Patterns that indicate invalid names
    invalid_name_patterns = [
        r'CERTIFICATE', r'RESUME', r'CV', r'CURRICULUM', r'VITAE',
        r'APPLICATION', r'PAGE \d+', r'^\d+$',
    ]
    
    candidates_table_data = []
    for candidate in st.session_state.metadata_list:
        name = candidate.get("name", "").strip()
        is_valid_name = False
        if name:
            name_upper = name.upper()
            is_valid_name = not any(re.search(pattern, name_upper) for pattern in invalid_name_patterns)
            if len(name.split()) < 1 or len(name) < 3:
                is_valid_name = False
        
        display_name = name if is_valid_name else candidate.get("filename", "Unknown")
        
        candidates_table_data.append({
            "Name": display_name,
            "Email": candidate.get("email", "N/A"),
            "Phone": candidate.get("phone", "N/A"),
            "Experience": f"{candidate.get('years_experience', 0)} yrs" if candidate.get('years_experience', 0) > 0 else "N/A",
            "Education": candidate.get("education_level", "N/A"),
            "Job Title": ", ".join(candidate.get("job_titles", [])[:2]) if candidate.get("job_titles") else "N/A",
            "Company": ", ".join(candidate.get("companies", [])[:2]) if candidate.get("companies") else "N/A",
            "Location": candidate.get("location", "N/A"),
            "Skills Count": len(candidate.get("skills", [])),
            "Skills": ", ".join(candidate.get("skills", [])[:5]) + ("..." if len(candidate.get("skills", [])) > 5 else ""),
            "Certifications": ", ".join(candidate.get("certifications", [])) if candidate.get("certifications") else "N/A",
            "Filename": candidate.get("filename", "N/A")
        })
    
    candidates_df = pd.DataFrame(candidates_table_data)
    st.dataframe(
        candidates_df,
        width='stretch',
        hide_index=True,
        height=400
    )
    
    # Summary Statistics - Mobile Responsive
    st.divider()
    st.markdown("### 📈 Summary Statistics")
    
    # Responsive columns: 3 on desktop, 1 on mobile
    col1, col2, col3 = st.columns(3)
    
    # Calculate summary stats
    valid_names_count = sum(1 for c in candidates_table_data if c["Name"] != "Unknown" and c["Name"] != c["Filename"])
    
    with col1:
        st.markdown("""
        **Contact Information:**
        - 📧 Email coverage: {:.1f}%
        - 📞 Phone coverage: {:.1f}%
        - ✅ Complete profiles: {:.1f}%
        """.format(
            (with_emails / total_count * 100) if total_count > 0 else 0,
            (with_phones / total_count * 100) if total_count > 0 else 0,
            (perfect_profiles / total_count * 100) if total_count > 0 else 0
        ))
    
    with col2:
        st.markdown("""
        **Skills Analysis:**
        - 🎯 Unique skills: {}
        - 📊 Total skill mentions: {}
        - 📈 Avg skills per candidate: {:.1f}
        """.format(
            total_unique_skills,
            total_skills,
            avg_skills
        ))
    
    with col3:
        st.markdown("""
        **Data Quality:**
        - ✅ Valid names: {}/{}
        - 📄 Total resumes: {}
        - 🎯 Avg completeness: {:.1f}/4.0
        """.format(
            valid_names_count,
            total_count,
            total_count,
            avg_completeness
        ))


# Main UI
st.title("📄 Resume RAG Chatbot")
st.markdown("Upload multiple resume PDFs and query them conversationally!")

# Security Warning (for production)
enable_persistence = os.getenv("ENABLE_PERSISTENCE", "false").lower() == "true"

if os.getenv("SHOW_SECURITY_WARNING", "true").lower() == "true":
    with st.expander("⚠️ Security & Privacy Notice", expanded=False):
        if enable_persistence:
            st.warning("""
            **Important Security Information:**
            
            - 🔒 **Data Storage**: Resumes and metadata are stored in `./faiss_store/` and `./metadata.pkl`
            - 📁 **Data Persistence**: ENABLED - Data persists after app restart (shared across users!)
            - ⚠️ **No Encryption**: Currently stored in plain text (not encrypted)
            - 🔐 **No Authentication**: Anyone with app URL can access (add authentication for production)
            - 🗑️ **Data Deletion**: Use "Clear All Data" button to remove all stored information
            
            **For Production Use:**
            - ✅ Add authentication system
            - ✅ Encrypt sensitive data
            - ✅ Use HTTPS/SSL
            - ✅ Implement access control
            
            See `SECURITY_AND_DATA.md` for details.
            """)
        else:
            st.info("""
            **Privacy & Data Storage:**
            
            - ✅ **Session-Only Storage**: Data is stored in memory only (not saved to disk)
            - ✅ **Private Sessions**: Each user's data is isolated (not shared with other users)
            - ✅ **Auto-Clear**: Data is cleared when you close the browser/refresh
            - 🔒 **No Persistent Files**: Resumes are NOT saved to disk (prevents cross-user data access)
            
            **Note**: To enable persistent storage (saves data across sessions), set `ENABLE_PERSISTENCE=true` in environment variables.
            """)

# Add custom CSS for mobile responsiveness and better UI styling
st.markdown("""
<style>
    /* Mobile responsiveness - Enhanced */
    @media screen and (max-width: 768px) {
        /* Main container */
        .main .block-container {
            padding-left: 0.5rem !important;
            padding-right: 0.5rem !important;
            max-width: 100% !important;
        }
        
        /* Sidebar on mobile - override desktop width, but respect collapsed state */
        [data-testid="stSidebar"][aria-expanded="true"] {
            min-width: 100% !important;
            max-width: 100% !important;
            width: 100% !important;
        }
        
        /* Collapsed sidebar on mobile - hide completely */
        [data-testid="stSidebar"][aria-expanded="false"] {
            width: 0 !important;
            min-width: 0 !important;
            max-width: 0 !important;
        }
        
        /* Sidebar content on mobile */
        [data-testid="stSidebar"][aria-expanded="true"] > div:first-child {
            padding: 0.75rem !important;
        }
        
        /* Headers - smaller on mobile */
        h1 {
            font-size: 1.5rem !important;
        }
        h2 {
            font-size: 1.3rem !important;
        }
        h3 {
            font-size: 1.1rem !important;
        }
        h4 {
            font-size: 1rem !important;
        }
        
        /* Chat messages mobile */
        [data-testid="stChatMessage"] {
            padding: 0.5rem !important;
            font-size: 0.9rem !important;
        }
        
        /* Analytics charts mobile - full width */
        .js-plotly-plot {
            width: 100% !important;
            max-width: 100% !important;
            height: auto !important;
            min-height: 300px !important;
        }
        
        /* Plotly container */
        .plotly {
            width: 100% !important;
            max-width: 100% !important;
        }
        
        /* Tabs mobile */
        [data-baseweb="tab-list"] {
            flex-wrap: wrap;
            gap: 0.25rem !important;
        }
        
        [data-baseweb="tab"] {
            padding: 0.5rem 0.75rem !important;
            font-size: 0.85rem !important;
            min-width: auto !important;
        }
        
        /* Metrics mobile - smaller */
        [data-testid="stMetricValue"] {
            font-size: 1.2rem !important;
        }
        
        [data-testid="stMetricLabel"] {
            font-size: 0.75rem !important;
        }
        
        /* Columns - stack on mobile */
        [data-testid="column"] {
            width: 100% !important;
            margin-bottom: 1rem !important;
            padding-left: 0 !important;
            padding-right: 0 !important;
        }
        
        /* Dataframes - scrollable */
        [data-testid="stDataFrame"] {
            font-size: 0.75rem !important;
            overflow-x: auto !important;
            display: block !important;
        }
        
        /* Tables - horizontal scroll */
        table {
            display: block !important;
            overflow-x: auto !important;
            white-space: nowrap !important;
            width: 100% !important;
            font-size: 0.75rem !important;
        }
        
        /* Buttons - full width on mobile */
        button {
            width: 100% !important;
            margin: 0.25rem 0 !important;
        }
        
        /* Markdown text - smaller */
        p, li, span {
            font-size: 0.9rem !important;
        }
        
        /* Expanders - smaller padding */
        [data-testid="stExpander"] {
            margin: 0.5rem 0 !important;
        }
        
        [data-testid="stExpander"] summary {
            font-size: 0.9rem !important;
            padding: 0.5rem !important;
        }
        
        /* Dividers - thinner */
        hr {
            margin: 0.75rem 0 !important;
        }
        
        /* Info boxes - smaller padding */
        .stAlert, .stInfo, .stSuccess, .stWarning, .stError {
            padding: 0.75rem !important;
            font-size: 0.85rem !important;
        }
        
        /* Metrics container */
        [data-testid="stMetricContainer"] {
            padding: 0.5rem !important;
            margin: 0.25rem 0 !important;
        }
    }
    
    /* Tablet responsiveness */
    @media screen and (min-width: 769px) and (max-width: 1024px) {
        .main .block-container {
            padding-left: 1rem !important;
            padding-right: 1rem !important;
        }
        
        [data-testid="column"] {
            padding: 0.5rem !important;
        }
        
        .js-plotly-plot {
            width: 100% !important;
            max-width: 100% !important;
        }
    }
    
    /* Sidebar toggle button - ensure visibility */
    button[kind="header"] {
        background: transparent !important;
        color: #ffffff !important;
    }
    
    /* Sidebar toggle button hover */
    button[kind="header"]:hover {
        background: rgba(255, 255, 255, 0.1) !important;
    }
    
    /* Sidebar styling - Dark theme to match main content */
    [data-testid="stSidebar"] {
        background: #262730 !important;
        color: #fafafa !important;
        transition: all 0.3s ease !important;
    }
    
    /* When sidebar is expanded, ensure full width */
    [data-testid="stSidebar"][aria-expanded="true"] {
        min-width: 21rem !important;
        width: 21rem !important;
        max-width: 21rem !important;
    }
    
    /* Hide collapsed sidebar completely - cleaner UI */
    [data-testid="stSidebar"][aria-expanded="false"] {
        width: 0 !important;
        min-width: 0 !important;
        max-width: 0 !important;
        overflow: hidden !important;
        padding: 0 !important;
        margin: 0 !important;
        border: none !important;
    }
    
    /* Hide sidebar content when collapsed */
    [data-testid="stSidebar"][aria-expanded="false"] > * {
        display: none !important;
        visibility: hidden !important;
        opacity: 0 !important;
    }
    
    /* Ensure sidebar content is properly sized when expanded */
    [data-testid="stSidebar"][aria-expanded="true"] > div:first-child {
        width: 100% !important;
        max-width: 100% !important;
        display: block !important;
        visibility: visible !important;
        opacity: 1 !important;
    }
    
    /* Sidebar content area */
    [data-testid="stSidebar"] > div:first-child {
        background: #262730 !important;
        width: 100% !important;
        max-width: 100% !important;
        padding: 1rem !important;
    }
    
    /* Sidebar scrollable content */
    [data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
        width: 100% !important;
    }
    
    /* Sidebar text visibility - light text on dark background */
    [data-testid="stSidebar"] * {
        color: #fafafa !important;
    }
    
    /* Override Streamlit's default sidebar background */
    [data-testid="stSidebar"] .css-1d391kg {
        background: #262730 !important;
    }
    
    /* Sidebar scrollbar - dark theme */
    [data-testid="stSidebar"]::-webkit-scrollbar {
        width: 8px;
    }
    
    [data-testid="stSidebar"]::-webkit-scrollbar-track {
        background: #1e1e24;
    }
    
    [data-testid="stSidebar"]::-webkit-scrollbar-thumb {
        background: #4a4a5a;
        border-radius: 4px;
    }
    
    [data-testid="stSidebar"]::-webkit-scrollbar-thumb:hover {
        background: #5a5a6a;
    }
    
    /* Sidebar headers - light color */
    [data-testid="stSidebar"] h1,
    [data-testid="stSidebar"] h2,
    [data-testid="stSidebar"] h3,
    [data-testid="stSidebar"] h4 {
        color: #4fc3f7 !important;
        font-weight: 600 !important;
    }
    
    /* Sidebar markdown text - light color */
    [data-testid="stSidebar"] p,
    [data-testid="stSidebar"] span,
    [data-testid="stSidebar"] div {
        color: #fafafa !important;
    }
    
    /* Sidebar input fields - dark theme */
    [data-testid="stSidebar"] input,
    [data-testid="stSidebar"] textarea,
    [data-testid="stSidebar"] select {
        background: #1e1e24 !important;
        color: #fafafa !important;
        border: 1px solid #4a4a5a !important;
    }
    
    /* Sidebar input focus - light blue accent */
    [data-testid="stSidebar"] input:focus,
    [data-testid="stSidebar"] textarea:focus,
    [data-testid="stSidebar"] select:focus {
        border: 2px solid #4fc3f7 !important;
        box-shadow: 0 0 0 0.2rem rgba(79, 195, 247, 0.25) !important;
        background: #2a2a35 !important;
    }
    
    /* Sidebar input placeholders */
    [data-testid="stSidebar"] input::placeholder,
    [data-testid="stSidebar"] textarea::placeholder {
        color: #9e9e9e !important;
    }
    
    /* Sidebar buttons */
    [data-testid="stSidebar"] button {
        color: #ffffff !important;
    }
    
    /* Sidebar button hover states */
    [data-testid="stSidebar"] button:hover {
        opacity: 0.9;
    }
    
    /* Sidebar info boxes - dark theme */
    [data-testid="stSidebar"] .stAlert {
        background: #1e1e24 !important;
        border: 1px solid #4a4a5a !important;
        color: #fafafa !important;
    }
    
    /* Sidebar success messages - dark theme */
    [data-testid="stSidebar"] .stSuccess {
        background: #1e4620 !important;
        color: #81c784 !important;
        border: 1px solid #4caf50 !important;
    }
    
    /* Sidebar info messages - dark theme */
    [data-testid="stSidebar"] .stInfo {
        background: #0d3a5f !important;
        color: #64b5f6 !important;
        border: 1px solid #2196f3 !important;
    }
    
    /* Sidebar warning messages - dark theme */
    [data-testid="stSidebar"] .stWarning {
        background: #5d4037 !important;
        color: #ffb74d !important;
        border: 1px solid #ff9800 !important;
    }
    
    /* Sidebar error messages - dark theme */
    [data-testid="stSidebar"] .stError {
        background: #5f2120 !important;
        color: #e57373 !important;
        border: 1px solid #f44336 !important;
    }
    
    /* Sidebar metrics - light text */
    [data-testid="stSidebar"] [data-testid="stMetricLabel"],
    [data-testid="stSidebar"] [data-testid="stMetricValue"] {
        color: #fafafa !important;
        font-weight: 500 !important;
    }
    
    /* Sidebar captions - lighter gray */
    [data-testid="stSidebar"] .stCaption {
        color: #b0b0b0 !important;
    }
    
    /* Sidebar expanders - dark theme */
    [data-testid="stSidebar"] [data-testid="stExpander"] {
        background: #1e1e24 !important;
        border: 1px solid #4a4a5a !important;
        border-radius: 0.5rem !important;
    }
    
    /* Sidebar expander header */
    [data-testid="stSidebar"] [data-testid="stExpander"] summary {
        background: #1e1e24 !important;
        color: #fafafa !important;
    }
    
    /* Sidebar expander content */
    [data-testid="stSidebar"] [data-testid="stExpander"] div {
        background: #1e1e24 !important;
        color: #fafafa !important;
    }
    
    /* Sidebar dividers - lighter for visibility */
    [data-testid="stSidebar"] hr {
        border-color: #4a4a5a !important;
        border-width: 1px !important;
    }
    
    /* Sidebar section backgrounds */
    [data-testid="stSidebar"] .element-container {
        background: transparent !important;
    }
    
    /* Sidebar file uploader - dark theme */
    [data-testid="stSidebar"] [data-testid="stFileUploader"] {
        background: #1e1e24 !important;
        border: 1px solid #4a4a5a !important;
        border-radius: 0.5rem !important;
        padding: 0.5rem !important;
    }
    
    /* Sidebar checkboxes and radio buttons */
    [data-testid="stSidebar"] input[type="checkbox"],
    [data-testid="stSidebar"] input[type="radio"] {
        accent-color: #4fc3f7 !important;
    }
    
    /* Sidebar labels */
    [data-testid="stSidebar"] label {
        color: #fafafa !important;
    }
    
    /* Sidebar select dropdowns */
    [data-testid="stSidebar"] select option {
        background: #1e1e24 !important;
        color: #fafafa !important;
    }
    
    /* Sidebar section backgrounds - ensure full width */
    [data-testid="stSidebar"] .element-container {
        background: transparent !important;
        width: 100% !important;
        max-width: 100% !important;
        overflow: visible !important;
    }
    
    /* Prevent sidebar content from being cut off */
    [data-testid="stSidebar"] * {
        box-sizing: border-box !important;
    }
    
    /* Sidebar file uploader and inputs - ensure full width */
    [data-testid="stSidebar"] [data-testid="stFileUploader"],
    [data-testid="stSidebar"] input,
    [data-testid="stSidebar"] textarea,
    [data-testid="stSidebar"] select,
    [data-testid="stSidebar"] button {
        width: 100% !important;
        max-width: 100% !important;
    }
    
    /* Better spacing for sidebar sections */
    .sidebar-section {
        margin-bottom: 1.5rem;
    }
    
    /* Chat interface styling */
    [data-testid="stChatMessage"] {
        padding: 1rem;
        margin: 0.5rem 0;
        border-radius: 0.5rem;
    }
    
    /* Chat input styling */
    [data-testid="stChatInput"] {
        position: sticky;
        bottom: 0;
        background: white;
        padding: 1rem;
        border-top: 1px solid #e0e0e0;
        z-index: 100;
    }
    
    /* Source documents expander */
    [data-testid="stExpander"] {
        margin: 0.5rem 0;
    }
    
    /* Analytics charts responsive */
    .js-plotly-plot {
        max-width: 100%;
        height: auto;
    }
    
    /* Metrics cards */
    [data-testid="stMetricContainer"] {
        padding: 0.75rem;
        border-radius: 0.5rem;
        background: #f8f9fa;
        margin: 0.5rem 0;
    }
    
    /* Tab styling */
    [data-baseweb="tab"] {
        padding: 0.75rem 1.5rem;
        font-weight: 500;
    }
    
    /* Better button spacing */
    button[kind="primary"] {
        margin: 0.5rem 0;
    }
    
    /* Chat message bubbles */
    .stChatMessage {
        animation: fadeIn 0.3s ease-in;
    }
    
    @keyframes fadeIn {
        from {
            opacity: 0;
            transform: translateY(10px);
        }
        to {
            opacity: 1;
            transform: translateY(0);
        }
    }
    
    /* Source document cards */
    .source-doc-card {
        background: #f8f9fa;
        padding: 1rem;
        border-radius: 0.5rem;
        margin: 0.5rem 0;
        border-left: 3px solid #1f77b4;
    }
    
    /* Analytics section spacing */
    .analytics-section {
        margin: 1.5rem 0;
    }
    
    /* Additional mobile optimizations for extra small screens */
    @media screen and (max-width: 480px) {
        /* Extra small screens */
        h1 {
            font-size: 1.3rem !important;
        }
        h2 {
            font-size: 1.1rem !important;
        }
        h3 {
            font-size: 1rem !important;
        }
        
        [data-testid="stMetricValue"] {
            font-size: 1rem !important;
        }
        
        .js-plotly-plot {
            min-height: 250px !important;
        }
        
        button {
            font-size: 0.85rem !important;
            padding: 0.5rem !important;
        }
        
        [data-testid="stDataFrame"] {
            font-size: 0.7rem !important;
        }
    }
</style>
""", unsafe_allow_html=True)

# Check for API keys and display status
try:
    from config import Config
    llm_provider = Config.LLM_PROVIDER
    llm_model = Config.LLM_MODEL
except ImportError:
    llm_provider = os.getenv("LLM_PROVIDER", "openai").lower()
    llm_model = os.getenv("LLM_MODEL", "gpt-4o-mini")

llm = get_llm()

# Load existing store on startup (only if persistence enabled)
load_existing_store()

# Enhanced Sidebar with perfect UI and mobile responsiveness
with st.sidebar:
    # App Logo/Header - Dark theme colors
    st.markdown("""
    <div style='text-align: center; padding: 1rem 0; border-bottom: 2px solid #4a4a5a; margin-bottom: 1.5rem;'>
        <h2 style='margin: 0; color: #4fc3f7;'>📄 Resume RAG</h2>
        <p style='margin: 0.5rem 0 0 0; color: #b0b0b0; font-size: 0.9rem;'>Intelligent Candidate Analysis</p>
    </div>
    """, unsafe_allow_html=True)
    
    # System Status Section - Simplified (no technical details)
    st.markdown("### 🔌 System Status")
    
    if llm:
        # Hide technical details - just show it's working
        st.success("✅ **AI Assistant**\n\n**Status:** Ready")
        st.info("🤖 **Intelligent Search**\n\nAI-powered responses enabled")
    else:
        st.warning("⚠️ **Basic Mode**\n\nAI features unavailable")
        st.info("💡 **Tip:**\n\nConfigure AI settings to enable intelligent search")
    
    st.divider()
    
    # Quick Stats Section
    total_candidates = len(st.session_state.metadata_list)
    processed_docs = st.session_state.get("documents_processed", False)
    
    st.markdown("### 📊 Quick Stats")
    
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Candidates", total_candidates, help="Total resumes loaded")
    with col2:
        status_icon = "✅" if processed_docs else "⏳"
        st.metric("Status", status_icon, help="Processing status")
    
    if total_candidates > 0:
        # Additional stats
        with_emails = sum(1 for c in st.session_state.metadata_list if c.get("email"))
        with_phones = sum(1 for c in st.session_state.metadata_list if c.get("phone"))
        total_skills = sum(len(c.get("skills", [])) for c in st.session_state.metadata_list)
        avg_skills = total_skills / total_candidates if total_candidates > 0 else 0
        
        st.markdown(f"""
        **📧 Email:** {with_emails}/{total_candidates}  
        **📞 Phone:** {with_phones}/{total_candidates}  
        **🛠️ Avg Skills:** {avg_skills:.1f}
        """)
    
    st.divider()
    
    # Upload Section
    st.markdown("### 📤 Upload Resumes")
    
    uploaded_files = st.file_uploader(
        "Choose PDF files",
        type=["pdf"],
        accept_multiple_files=True,
        help="Upload one or more resume PDFs. Supports multiple files at once."
    )
    
    if uploaded_files:
        st.info(f"📎 **{len(uploaded_files)} file(s) selected**")
        for file in uploaded_files[:3]:  # Show first 3
            st.caption(f"• {file.name}")
        if len(uploaded_files) > 3:
            st.caption(f"... and {len(uploaded_files) - 3} more")
    
    use_ocr = st.checkbox(
        "🔍 Use OCR (for scanned PDFs)",
        value=False,
        help="Enable OCR for scanned/image-based PDFs. Slower but more accurate for non-text PDFs."
    )
    
    if st.button("🚀 Process Resumes", type="primary", use_container_width=True):
        if uploaded_files:
            process_uploaded_pdfs(uploaded_files, use_ocr)
        else:
            st.warning("⚠️ Please upload at least one PDF file")
    
    st.divider()
    
    # Advanced Filters Section
    st.markdown("### 🔍 Advanced Filters")
    
    with st.expander("🎯 Filter Options", expanded=False):
        name_filter = st.text_input(
            "👤 Filter by Name",
            value="",
            placeholder="Enter candidate name...",
            help="Search candidates by name"
        )
        
        skill_filter = st.text_input(
            "🛠️ Filter by Skill",
            value="",
            placeholder="e.g., Python, React, AWS...",
            help="Search candidates by skill"
        )
        
        # Experience filter
        exp_filter = st.selectbox(
            "📊 Experience Level",
            ["All", "Entry (0-2 yrs)", "Mid (3-5 yrs)", "Senior (6-10 yrs)", "Expert (10+ yrs)"],
            help="Filter by years of experience"
        )
        
        # Education filter
        edu_filter = st.selectbox(
            "🎓 Education Level",
            ["All", "PhD", "Master's", "Bachelor's", "Associate's", "Diploma"],
            help="Filter by education level"
        )
        
        use_ranking = st.checkbox(
            "⭐ Rank by Relevance",
            value=False,
            help="Sort results by relevance score"
        )
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🔎 Apply Filters", use_container_width=True):
                filtered = filter_candidates(name_filter, skill_filter)
                
                # Apply experience filter
                if exp_filter != "All":
                    exp_ranges = {
                        "Entry (0-2 yrs)": (0, 2),
                        "Mid (3-5 yrs)": (3, 5),
                        "Senior (6-10 yrs)": (6, 10),
                        "Expert (10+ yrs)": (11, 100)
                    }
                    min_exp, max_exp = exp_ranges[exp_filter]
                    filtered = [c for c in filtered if min_exp <= c.get("years_experience", 0) <= max_exp]
                
                # Apply education filter
                if edu_filter != "All":
                    filtered = [c for c in filtered if c.get("education_level", "") == edu_filter]
                
                # Apply ranking if enabled
                if use_ranking and filtered:
                    query_text = f"{name_filter} {skill_filter}".strip()
                    if query_text:
                        ranked_results = rank_candidates(filtered, query_text)
                        st.session_state.filtered_candidates = [candidate for candidate, score in ranked_results]
                        st.success(f"✅ Found and ranked {len(st.session_state.filtered_candidates)} candidate(s)")
                    else:
                        st.session_state.filtered_candidates = filtered
                else:
                    st.session_state.filtered_candidates = filtered
                    st.success(f"✅ Found {len(filtered)} candidate(s)")
        
        with col2:
            if st.button("🔄 Clear Filters", use_container_width=True):
                st.session_state.filtered_candidates = []
                st.rerun()
    
    st.divider()
    
    # Candidates List Section
    st.markdown("### 👥 Candidates")
    
    candidates_to_show = st.session_state.get("filtered_candidates", st.session_state.metadata_list)
    
    if candidates_to_show:
        st.caption(f"Showing {len(candidates_to_show)} candidate(s)")
        
        # Scrollable container for candidates
        for idx, candidate in enumerate(candidates_to_show[:10]):  # Limit to 10 for performance
            name = candidate.get('name', candidate.get('filename', 'Unknown'))
            is_valid_name = name and name != candidate.get('filename', '')
            
            with st.expander(f"📄 {name[:30]}{'...' if len(name) > 30 else ''}", expanded=False):
                # Candidate details
                col1, col2 = st.columns(2)
                
                with col1:
                    st.markdown(f"**📧 Email:**\n{candidate.get('email', 'N/A')}")
                    st.markdown(f"**📞 Phone:**\n{candidate.get('phone', 'N/A')}")
                
                with col2:
                    exp_years = candidate.get('years_experience', 0)
                    st.markdown(f"**📊 Experience:**\n{exp_years} yrs" if exp_years > 0 else "**📊 Experience:**\nN/A")
                    st.markdown(f"**🎓 Education:**\n{candidate.get('education_level', 'N/A')}")
                
                # Skills
                skills = candidate.get('skills', [])
                if skills:
                    st.markdown(f"**🛠️ Skills:** {len(skills)}")
                    skill_tags = ", ".join(skills[:5])
                    st.caption(skill_tags + ("..." if len(skills) > 5 else ""))
                
                # Additional info
                if candidate.get('job_titles'):
                    st.markdown(f"**💼 Title:** {', '.join(candidate.get('job_titles', [])[:2])}")
                if candidate.get('companies'):
                    st.markdown(f"**🏢 Company:** {', '.join(candidate.get('companies', [])[:2])}")
                if candidate.get('location'):
                    st.markdown(f"**📍 Location:** {candidate.get('location')}")
                if candidate.get('certifications'):
                    st.markdown(f"**🏆 Certifications:** {', '.join(candidate.get('certifications', [])[:3])}")
                
                st.caption(f"📁 File: {candidate.get('filename', 'N/A')}")
        
        if len(candidates_to_show) > 10:
            st.info(f"💡 Showing first 10 of {len(candidates_to_show)} candidates. Use filters to narrow down.")
    else:
        st.info("📭 No candidates loaded.\n\nUpload resumes to get started!")
    
    st.divider()
    
    # Export Section
    st.markdown("### 📥 Export Data")
    
    candidates_to_export = st.session_state.get("filtered_candidates", st.session_state.metadata_list)
    
    if candidates_to_export:
        col1, col2 = st.columns(2)
        
        with col1:
            if st.button("📊 Export CSV", use_container_width=True):
                try:
                    export_path = "candidates_export.csv"
                    if export_candidates_to_csv(candidates_to_export, export_path):
                        with open(export_path, 'rb') as f:
                            st.download_button(
                                label="⬇️ Download",
                                data=f,
                                file_name="candidates_export.csv",
                                mime="text/csv",
                                width='stretch'
                            )
                        st.success(f"✅ Exported {len(candidates_to_export)} candidates")
                    else:
                        st.error("❌ Export failed")
                except Exception as e:
                    st.error(f"❌ Error: {e}")
        
        with col2:
            st.caption(f"📦 {len(candidates_to_export)} candidates ready")
    else:
        st.info("📭 No data to export")
    
    st.divider()
    
    # Data Management Section
    st.markdown("### 🗑️ Data Management")
    
    if st.button("🗑️ Clear All Data", type="secondary", use_container_width=True):
        if st.session_state.get("confirm_delete", False):
            try:
                # Delete vector store
                if os.path.exists(VECTOR_STORE_DIR):
                    shutil.rmtree(VECTOR_STORE_DIR)
                    logger.info("Vector store deleted")
                
                # Delete metadata
                if os.path.exists(METADATA_FILE):
                    os.remove(METADATA_FILE)
                    logger.info("Metadata file deleted")
                
                # Clear session state
                st.session_state.vector_store = None
                st.session_state.metadata_list = []
                st.session_state.documents_processed = False
                st.session_state.chat_history = []
                st.session_state.filtered_candidates = []
                st.session_state.confirm_delete = False
                
                st.success("✅ All data cleared!")
                st.rerun()
            except Exception as e:
                st.error(f"❌ Error: {e}")
        else:
            st.session_state.confirm_delete = True
            st.warning("⚠️ Click again to confirm deletion")
    
    # Footer - Dark theme colors
    st.divider()
    st.markdown("""
    <div style='text-align: center; padding: 1rem 0; color: #b0b0b0; font-size: 0.8rem;'>
        <p>📄 Resume RAG System</p>
        <p>Version 2.0</p>
    </div>
    """, unsafe_allow_html=True)

# Main chat area
if st.session_state.documents_processed and st.session_state.vector_store:
    # Add tabs for Chat and Analytics with better styling
    tab1, tab2 = st.tabs(["💬 Chat", "📊 Analytics"])
    
    with tab1:
        # Enhanced Chat Header
        col1, col2 = st.columns([3, 1])
        with col1:
            st.markdown("### 💬 Chat with Resumes")
            st.caption("Ask questions about the uploaded resumes and get AI-powered answers")
        with col2:
            if st.button("🗑️ Clear Chat", use_container_width=True, help="Clear all chat history"):
                st.session_state.chat_history = []
                st.rerun()
        
        st.divider()
        
        # Chat Container with better styling
        chat_container = st.container()
        
        with chat_container:
            # Display chat history with enhanced UI
            if st.session_state.chat_history:
                for idx, message in enumerate(st.session_state.chat_history):
                    with st.chat_message(message["role"]):
                        # Enhanced message display
                        st.markdown(message["content"])
                        
                        # Show source documents in a better format
                        if "sources" in message and message["sources"]:
                            with st.expander(f"📎 View Sources ({len(message['sources'])} documents)", expanded=False):
                                # Group sources by candidate
                                candidates_sources = {}
                                for source in message["sources"][:10]:  # Limit to 10
                                    candidate_name = source.metadata.get('name', source.metadata.get('filename', 'Unknown'))
                                    if candidate_name not in candidates_sources:
                                        candidates_sources[candidate_name] = []
                                    candidates_sources[candidate_name].append(source)
                                
                                for candidate_name, sources in candidates_sources.items():
                                    st.markdown(f"**👤 {candidate_name}**")
                                    
                                    # Show candidate metadata
                                    if sources[0].metadata.get('email'):
                                        st.caption(f"📧 {sources[0].metadata.get('email')}")
                                    if sources[0].metadata.get('skills'):
                                        st.caption(f"🛠️ Skills: {sources[0].metadata.get('skills', 'N/A')[:100]}")
                                    
                                    # Show snippets
                                    for i, source in enumerate(sources[:3], 1):
                                        st.markdown(f"**Snippet {i}:**")
                                        st.info(f"{source.page_content[:250]}...")
                                    
                                    if len(sources) > 3:
                                        st.caption(f"... and {len(sources) - 3} more snippets")
                                    
                                    st.divider()
            else:
                # Welcome message when no chat history
                st.info("""
                👋 **Welcome to Resume RAG Chatbot!**
                
                **Try asking:**
                - "Who has experience with Python?"
                - "Show me candidates with AWS certification"
                - "Find developers with 5+ years of experience"
                - "What skills do the candidates have?"
                
                Type your question in the chat input below to get started!
                """)
        
        # Enhanced Chat Input
        st.divider()
        query = st.chat_input(
            "💬 Ask a question about the resumes... (e.g., 'Who has Python experience?')",
            key="chat_input"
        )
    
        if query:
            # Add user message to chat
            st.session_state.chat_history.append({"role": "user", "content": query})
            with st.chat_message("user"):
                st.markdown(query)
            
            # Get response with enhanced UI
            with st.chat_message("assistant"):
                with st.spinner("🔍 Searching resumes and generating response..."):
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
                            st.error(f"❌ Error: {e}")
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
                                    answer += f"📧 Email: {docs[0].metadata.get('email')}\n"
                                answer += f"📄 Relevant sections:\n"
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
                                answer += f"📧 Email: {docs[0].metadata.get('email')}\n"
                            answer += f"📄 Relevant sections:\n"
                            for i, doc in enumerate(docs[:3], 1):
                                answer += f"  {i}. {doc.page_content[:300]}...\n\n"
                    else:
                        answer = "❌ No relevant information found in the resumes. Try rephrasing your question."
                    
                    # Display answer with better formatting
                    st.markdown(answer)
                    
                    # Show source documents in enhanced format
                    if source_docs:
                        with st.expander(f"📎 Source Documents ({len(source_docs)} found)", expanded=False):
                            # Group by candidate
                            candidates_sources = {}
                            for doc in source_docs[:10]:  # Limit to 10
                                candidate_name = doc.metadata.get('name', doc.metadata.get('filename', 'Unknown'))
                                if candidate_name not in candidates_sources:
                                    candidates_sources[candidate_name] = []
                                candidates_sources[candidate_name].append(doc)
                            
                            for candidate_name, docs in candidates_sources.items():
                                # Candidate header
                                st.markdown(f"**👤 {candidate_name}**")
                                
                                # Metadata in columns for mobile responsiveness
                                col1, col2 = st.columns(2)
                                with col1:
                                    if docs[0].metadata.get('email'):
                                        st.caption(f"📧 {docs[0].metadata.get('email')}")
                                    if docs[0].metadata.get('phone'):
                                        st.caption(f"📞 {docs[0].metadata.get('phone')}")
                                with col2:
                                    if docs[0].metadata.get('years_experience', 0) > 0:
                                        st.caption(f"📊 {docs[0].metadata.get('years_experience')} yrs exp")
                                    if docs[0].metadata.get('education_level'):
                                        st.caption(f"🎓 {docs[0].metadata.get('education_level')}")
                                
                                # Skills
                                if docs[0].metadata.get('skills'):
                                    skills_display = docs[0].metadata.get('skills', 'N/A')
                                    if len(skills_display) > 100:
                                        skills_display = skills_display[:100] + "..."
                                    st.caption(f"🛠️ {skills_display}")
                                
                                # Show snippets
                                for i, doc in enumerate(docs[:3], 1):
                                    st.markdown(f"**📄 Snippet {i}:**")
                                    st.info(f"{doc.page_content[:300]}...")
                                
                                if len(docs) > 3:
                                    st.caption(f"💡 ... and {len(docs) - 3} more snippets from this candidate")
                                
                                st.divider()
                    
                    # Add assistant response to chat history
                    st.session_state.chat_history.append({
                        "role": "assistant",
                        "content": answer,
                        "sources": source_docs
                    })
    
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


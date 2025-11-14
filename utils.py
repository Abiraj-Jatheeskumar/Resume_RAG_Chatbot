"""
Utility functions for RAG chatbot: PDF extraction, metadata parsing, embeddings, and FAISS operations.
"""
import os
import re
import io
import logging
from typing import List, Dict, Optional, Tuple
import PyPDF2
from pdf2image import convert_from_path
import pytesseract
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
try:
    from langchain_community.embeddings import HuggingFaceEmbeddings
    HUGGINGFACE_AVAILABLE = True
except ImportError:
    HUGGINGFACE_AVAILABLE = False
try:
    from langchain_openai import AzureChatOpenAI
    AZURE_OPENAI_AVAILABLE = True
except ImportError:
    AZURE_OPENAI_AVAILABLE = False
try:
    from langchain_anthropic import ChatAnthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
try:
    from langchain_ollama import ChatOllama
    OLLAMA_AVAILABLE = True
except ImportError:
    OLLAMA_AVAILABLE = False
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
import pickle

logger = logging.getLogger(__name__)


def extract_text_from_pdf(pdf_path: str, use_ocr: bool = False) -> str:
    """
    Extract text from PDF using PyPDF2, with OCR fallback if needed.
    
    Args:
        pdf_path: Path to PDF file
        use_ocr: Whether to use OCR if text extraction fails
        
    Returns:
        Extracted text string
    """
    text = ""
    
    try:
        # Try PyPDF2 first
        with open(pdf_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            for page in pdf_reader.pages:
                text += page.extract_text() + "\n"
        
        # If text extraction yields very little text, use OCR
        if use_ocr or len(text.strip()) < 100:
            try:
                images = convert_from_path(pdf_path)
                ocr_text = ""
                for image in images:
                    ocr_text += pytesseract.image_to_string(image) + "\n"
                if len(ocr_text.strip()) > len(text.strip()):
                    text = ocr_text
            except Exception as e:
                print(f"OCR failed: {e}, using PyPDF2 text")
                
    except Exception as e:
        print(f"Error extracting text from {pdf_path}: {e}")
        if use_ocr:
            try:
                images = convert_from_path(pdf_path)
                for image in images:
                    text += pytesseract.image_to_string(image) + "\n"
            except Exception as ocr_error:
                print(f"OCR also failed: {ocr_error}")
    
    return text


def extract_metadata(text: str, filename: str) -> Dict[str, str]:
    """
    Extract metadata from resume text: name, email, phone, skills.
    
    Args:
        text: Resume text content
        filename: Original filename
        
    Returns:
        Dictionary with metadata fields
    """
    metadata = {
        "filename": filename,
        "name": "",
        "email": "",
        "phone": "",
        "skills": []
    }
    
    # Extract email
    email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    emails = re.findall(email_pattern, text)
    if emails:
        metadata["email"] = emails[0]
    
    # Extract phone (various formats)
    phone_patterns = [
        r'\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}',
        r'\+\d{1,3}[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}',
        r'\d{3}[-.\s]?\d{3}[-.\s]?\d{4}'
    ]
    for pattern in phone_patterns:
        phones = re.findall(pattern, text)
        if phones:
            metadata["phone"] = phones[0]
            break
    
    # Extract name - improved logic to filter out headers
    # Common patterns to exclude (headers, titles, etc.)
    exclude_patterns = [
        r'CERTIFICATE',
        r'RESUME',
        r'CV',
        r'CURRICULUM',
        r'VITAE',
        r'APPLICATION',
        r'COVER LETTER',
        r'PAGE \d+',
        r'\d+/\d+/\d+',  # Dates
        r'\d{4}',  # Years alone
        r'PHONE',
        r'EMAIL',
        r'ADDRESS',
        r'CONTACT',
        r'OBJECTIVE',
        r'SUMMARY',
        r'EXPERIENCE',
        r'EDUCATION',
        r'SKILLS',
        r'PROJECT',
        r'REFERENCES',
    ]
    
    # Try to extract name from filename first (often contains name)
    filename_base = os.path.splitext(filename)[0]  # Remove extension
    # Remove common separators and check if it looks like a name
    filename_clean = re.sub(r'[-_]', ' ', filename_base).strip()
    filename_parts = filename_clean.split()
    # If filename has 2-3 capitalized words, it might be a name
    if 2 <= len(filename_parts) <= 3:
        potential_name = ' '.join(filename_parts)
        # Check if it looks like a name (starts with capital, no numbers, not too long)
        if re.match(r'^[A-Z][a-z]+(\s+[A-Z][a-z]+)+$', potential_name) and len(potential_name) < 50:
            metadata["name"] = potential_name
    
    # If no name from filename, try to extract from text
    if not metadata["name"]:
        lines = text.split('\n')[:15]  # Check first 15 lines
        
        for line in lines:
            line = line.strip()
            # Skip empty lines
            if not line:
                continue
            
            # Skip lines that are clearly not names
            line_upper = line.upper()
            is_excluded = any(re.search(pattern, line_upper) for pattern in exclude_patterns)
            
            if is_excluded:
                continue
            
            # Skip lines with email
            if '@' in line:
                continue
            
            # Skip lines that are too long (likely paragraphs)
            if len(line) > 80:
                continue
            
            # Skip lines with only numbers or special characters
            if re.match(r'^[\d\s\W]+$', line):
                continue
            
            # Look for name-like patterns: 2-4 words, starts with capital letter(s)
            words = line.split()
            if 2 <= len(words) <= 4:
                # Check if it looks like a name (proper capitalization)
                # At least first word starts with capital, not all caps (unless 2 words)
                first_word = words[0]
                if first_word and first_word[0].isupper():
                    # Exclude if it's all caps and has more than 2 words
                    if len(words) > 2 and line.isupper():
                        continue
                    # Check if it contains typical name patterns (letters, spaces, hyphens, apostrophes)
                    if re.match(r'^[A-Z][a-zA-Z\s\-\']+$', line):
                        metadata["name"] = line
                        break
            
            # Also try single capitalized word (could be last name only)
            elif len(words) == 1 and words[0][0].isupper() and len(words[0]) > 2:
                if re.match(r'^[A-Z][a-z]+$', words[0]):
                    metadata["name"] = words[0]
                    break
    
    # Fallback: use filename if still no name found
    if not metadata["name"]:
        # Clean filename and use as fallback
        filename_clean = re.sub(r'[-_.]', ' ', filename_base).strip()
        if filename_clean:
            metadata["name"] = filename_clean
    
    # Extract skills (common tech keywords)
    common_skills = [
        'Python', 'JavaScript', 'Java', 'React', 'Node.js', 'Angular', 'Vue',
        'SQL', 'MongoDB', 'PostgreSQL', 'AWS', 'Docker', 'Kubernetes',
        'Git', 'Linux', 'Django', 'Flask', 'Spring', 'TypeScript', 'HTML',
        'CSS', 'Machine Learning', 'Deep Learning', 'TensorFlow', 'PyTorch',
        'C++', 'C#', '.NET', 'PHP', 'Ruby', 'Go', 'Rust', 'Swift', 'Kotlin'
    ]
    
    text_upper = text.upper()
    found_skills = []
    for skill in common_skills:
        if skill.upper() in text_upper:
            found_skills.append(skill)
    
    metadata["skills"] = found_skills[:10]  # Limit to 10 skills
    
    return metadata


def get_embeddings():
    """
    Initialize embeddings: OpenAI if API key exists, otherwise HuggingFace.
    Uses configuration from config.py if available.
    
    Returns:
        Embeddings instance
    """
    try:
        from config import Config
        embedding_provider = Config.EMBEDDING_MODEL
        model_name = Config.EMBEDDING_MODEL_NAME
    except ImportError:
        embedding_provider = os.getenv("EMBEDDING_MODEL", "openai")
        model_name = os.getenv("EMBEDDING_MODEL_NAME", "sentence-transformers/all-MiniLM-L6-v2")
    
    openai_api_key = os.getenv("OPENAI_API_KEY")
    azure_key = os.getenv("AZURE_OPENAI_KEY")
    azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    azure_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT"))
    azure_api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2025-01-01-preview")
    
    # Try Azure OpenAI embeddings first if available
    if (embedding_provider == "azure_openai" or azure_key) and azure_endpoint and azure_deployment:
        try:
            from langchain_openai import AzureOpenAIEmbeddings
            logger.info(f"Using Azure OpenAI embeddings: {azure_deployment} at {azure_endpoint}")
            return AzureOpenAIEmbeddings(
                azure_deployment=azure_deployment,
                azure_endpoint=azure_endpoint,
                api_key=azure_key,
                api_version=azure_api_version
            )
        except Exception as e:
            logger.warning(f"Failed to initialize Azure OpenAI embeddings: {e}, falling back")
    
    # Try standard OpenAI embeddings
    if embedding_provider == "openai" and openai_api_key:
        try:
            logger.info("Using OpenAI embeddings")
            return OpenAIEmbeddings()
        except Exception as e:
            logger.warning(f"Failed to initialize OpenAI embeddings: {e}, falling back to local")
    
    # Fallback to sentence-transformers
    if HUGGINGFACE_AVAILABLE:
        try:
            logger.info(f"Using HuggingFace embeddings with model: {model_name}")
            return HuggingFaceEmbeddings(
                model_name=model_name
            )
        except Exception as e:
            logger.error(f"Failed to initialize HuggingFace embeddings: {e}")
            raise ImportError("Please install sentence-transformers: pip install sentence-transformers")
    else:
        raise ImportError("Please install sentence-transformers: pip install sentence-transformers")


def get_llm():
    """
    Get LLM instance based on configuration.
    Supports Azure OpenAI, OpenAI, Anthropic Claude, and Ollama.
    
    Returns:
        LLM instance or None if not available
    """
    try:
        from config import Config
        provider = Config.LLM_PROVIDER
        model = Config.LLM_MODEL
        temperature = 0
    except ImportError:
        provider = os.getenv("LLM_PROVIDER", "openai").lower()
        model = os.getenv("LLM_MODEL", "gpt-4o-mini")
        temperature = 0
    
    # Azure OpenAI (priority check since user has this)
    azure_key = os.getenv("AZURE_OPENAI_KEY")
    azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    azure_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
    azure_api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2025-01-01-preview")
    
    if provider == "azure_openai" or (azure_key and azure_endpoint and azure_deployment):
        if azure_key and azure_endpoint and azure_deployment:
            try:
                logger.info(f"Using Azure OpenAI LLM: {azure_deployment} at {azure_endpoint}")
                return AzureChatOpenAI(
                    azure_deployment=azure_deployment,
                    azure_endpoint=azure_endpoint,
                    api_key=azure_key,
                    api_version=azure_api_version,
                    temperature=temperature
                )
            except Exception as e:
                logger.error(f"Failed to initialize Azure OpenAI LLM: {e}")
    
    # OpenAI (standard)
    if provider == "openai":
        openai_api_key = os.getenv("OPENAI_API_KEY")
        if openai_api_key:
            try:
                from langchain_openai import ChatOpenAI
                logger.info(f"Using OpenAI LLM: {model}")
                return ChatOpenAI(
                    model=model,
                    temperature=temperature,
                    api_key=openai_api_key
                )
            except Exception as e:
                logger.error(f"Failed to initialize OpenAI LLM: {e}")
    
    # Anthropic Claude
    elif provider == "anthropic" and ANTHROPIC_AVAILABLE:
        anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")
        if anthropic_api_key:
            try:
                logger.info(f"Using Anthropic LLM: {model}")
                return ChatAnthropic(
                    model=model,
                    temperature=temperature,
                    api_key=anthropic_api_key
                )
            except Exception as e:
                logger.error(f"Failed to initialize Anthropic LLM: {e}")
    
    # Ollama (local)
    elif provider == "ollama" and OLLAMA_AVAILABLE:
        try:
            ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
            logger.info(f"Using Ollama LLM: {model} at {ollama_base_url}")
            return ChatOllama(
                model=model,
                base_url=ollama_base_url,
                temperature=temperature
            )
        except Exception as e:
            logger.error(f"Failed to initialize Ollama LLM: {e}")
    
    logger.warning("No LLM provider available. Using basic retrieval mode.")
    return None


def create_vector_store(documents: List[Document], embeddings, persist_dir: Optional[str] = None) -> FAISS:
    """
    Create FAISS vector store from documents.
    
    Args:
        documents: List of Document objects
        embeddings: Embeddings instance
        persist_dir: Optional directory to persist the store
        
    Returns:
        FAISS vector store
    """
    if not documents:
        raise ValueError("No documents provided")
    
    vector_store = FAISS.from_documents(documents, embeddings)
    
    if persist_dir:
        os.makedirs(persist_dir, exist_ok=True)
        vector_store.save_local(persist_dir)
    
    return vector_store


def load_vector_store(embeddings, persist_dir: str) -> Optional[FAISS]:
    """
    Load existing FAISS vector store.
    
    Args:
        embeddings: Embeddings instance
        persist_dir: Directory where store is persisted
        
    Returns:
        FAISS vector store or None if not found
    """
    try:
        if os.path.exists(persist_dir):
            # Check if index file exists
            index_file = os.path.join(persist_dir, "index.faiss")
            if os.path.exists(index_file):
                return FAISS.load_local(persist_dir, embeddings, allow_dangerous_deserialization=True)
    except Exception as e:
        print(f"Error loading vector store: {e}")
    return None


def chunk_text(text: str, chunk_size: Optional[int] = None, chunk_overlap: Optional[int] = None) -> List[str]:
    """
    Split text into chunks for embedding.
    Uses configuration from config.py if available.
    
    Args:
        text: Text to chunk
        chunk_size: Size of each chunk (uses config if None)
        chunk_overlap: Overlap between chunks (uses config if None)
        
    Returns:
        List of text chunks
    """
    try:
        from config import Config
        if chunk_size is None:
            chunk_size = Config.MAX_CHUNK_SIZE
        if chunk_overlap is None:
            chunk_overlap = Config.CHUNK_OVERLAP
    except ImportError:
        if chunk_size is None:
            chunk_size = int(os.getenv("MAX_CHUNK_SIZE", "1000"))
        if chunk_overlap is None:
            chunk_overlap = int(os.getenv("CHUNK_OVERLAP", "200"))
    
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len
    )
    return text_splitter.split_text(text)


def rank_candidates(candidates: List[Dict], query: str, skills_weights: Optional[Dict[str, float]] = None) -> List[Tuple[Dict, float]]:
    """
    Rank candidates based on relevance to query and metadata completeness.
    
    Args:
        candidates: List of candidate metadata dictionaries
        query: Search query
        skills_weights: Optional weights for specific skills
        
    Returns:
        List of (candidate, score) tuples sorted by score (descending)
    """
    if not candidates:
        return []
    
    query_lower = query.lower()
    query_skills = [skill.lower() for skill in query_lower.split() if len(skill) > 3]
    
    ranked = []
    for candidate in candidates:
        score = 0.0
        
        # Name match
        name = candidate.get("name", "").lower()
        if query_lower in name:
            score += 10.0
        
        # Email match
        email = candidate.get("email", "").lower()
        if query_lower in email:
            score += 5.0
        
        # Skills match
        skills = [skill.lower() for skill in candidate.get("skills", [])]
        for query_skill in query_skills:
            for skill in skills:
                if query_skill in skill or skill in query_skill:
                    weight = skills_weights.get(skill, 1.0) if skills_weights else 1.0
                    score += 3.0 * weight
        
        # Metadata completeness bonus
        completeness = 0
        if candidate.get("name"):
            completeness += 1
        if candidate.get("email"):
            completeness += 1
        if candidate.get("phone"):
            completeness += 1
        if candidate.get("skills"):
            completeness += min(len(candidate.get("skills", [])), 5) * 0.2
        
        score += completeness
        
        ranked.append((candidate, score))
    
    # Sort by score descending
    ranked.sort(key=lambda x: x[1], reverse=True)
    return ranked


def export_candidates_to_csv(candidates: List[Dict], filepath: str) -> bool:
    """
    Export candidates to CSV file.
    
    Args:
        candidates: List of candidate metadata dictionaries
        filepath: Path to output CSV file
        
    Returns:
        True if successful, False otherwise
    """
    try:
        import csv
        
        if not candidates:
            logger.warning("No candidates to export")
            return False
        
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            fieldnames = ['name', 'email', 'phone', 'skills', 'filename']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            
            writer.writeheader()
            for candidate in candidates:
                writer.writerow({
                    'name': candidate.get('name', ''),
                    'email': candidate.get('email', ''),
                    'phone': candidate.get('phone', ''),
                    'skills': ', '.join(candidate.get('skills', [])),
                    'filename': candidate.get('filename', '')
                })
        
        logger.info(f"Exported {len(candidates)} candidates to {filepath}")
        return True
    except Exception as e:
        logger.error(f"Failed to export candidates: {e}")
        return False


def get_skills_distribution(candidates: List[Dict]) -> Dict[str, int]:
    """
    Get distribution of skills across all candidates.
    
    Args:
        candidates: List of candidate metadata dictionaries
        
    Returns:
        Dictionary mapping skill names to count
    """
    skills_count = {}
    for candidate in candidates:
        for skill in candidate.get("skills", []):
            skills_count[skill] = skills_count.get(skill, 0) + 1
    return skills_count


def process_resume_pdf(pdf_path: str, use_ocr: bool = False) -> Tuple[str, Dict[str, str]]:
    """
    Process a single resume PDF: extract text and metadata.
    
    Args:
        pdf_path: Path to PDF file
        use_ocr: Whether to use OCR
        
    Returns:
        Tuple of (text, metadata)
    """
    text = extract_text_from_pdf(pdf_path, use_ocr)
    filename = os.path.basename(pdf_path)
    metadata = extract_metadata(text, filename)
    return text, metadata


def save_metadata(metadata_list: List[Dict], filepath: str):
    """Save metadata list to pickle file."""
    with open(filepath, 'wb') as f:
        pickle.dump(metadata_list, f)


def load_metadata(filepath: str) -> List[Dict]:
    """Load metadata list from pickle file."""
    try:
        with open(filepath, 'rb') as f:
            return pickle.load(f)
    except Exception as e:
        print(f"Error loading metadata: {e}")
        return []


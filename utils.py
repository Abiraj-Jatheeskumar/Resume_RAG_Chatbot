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
    # Try new langchain-huggingface package first
    from langchain_huggingface import HuggingFaceEmbeddings
    HUGGINGFACE_AVAILABLE = True
except ImportError:
    try:
        # Fallback to deprecated langchain_community version
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
    Extract metadata from resume text: name, email, phone, skills, experience, education, etc.
    
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
        "skills": [],
        "years_experience": 0,
        "education_level": "",
        "job_titles": [],
        "companies": [],
        "location": "",
        "certifications": []
    }
    
    # Extract email
    email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    emails = re.findall(email_pattern, text)
    if emails:
        metadata["email"] = emails[0]
    
    # Extract phone (various formats including international)
    phone_patterns = [
        r'\+\d{1,3}[-.\s]?\(?\d{1,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}',  # International: +1-234-567-8900
        r'\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}',  # US: (123) 456-7890
        r'\d{3}[-.\s]?\d{3}[-.\s]?\d{4}',  # US: 123-456-7890
        r'\d{3}[-\s]\d{3}[-\s]\d{4}',  # Format: 123 456 7890
        r'\d{10}',  # No separator: 1234567890
        r'\+\d{1,4}[-\s]?\d{6,14}',  # Generic international
    ]
    for pattern in phone_patterns:
        phones = re.findall(pattern, text)
        if phones:
            # Filter out numbers that look like dates or other data
            phone = phones[0].strip()
            # Skip if it looks like a year (4 digits only)
            if re.match(r'^\d{4}$', phone):
                continue
            metadata["phone"] = phone
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
    # Remove common resume-related words from filename
    filename_clean = re.sub(r'\b(resume|cv|curriculum|vitae|intern|internship|fresher|experienced|updated|final|latest)\b', '', filename_clean, flags=re.IGNORECASE)
    filename_clean = re.sub(r'\s+', ' ', filename_clean).strip()
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
            if len(words) == 1 and words[0][0].isupper() and len(words[0]) > 2:
                if re.match(r'^[A-Z][a-z]+$', words[0]):
                    metadata["name"] = words[0]
                    break
    
    # Fallback: use filename if still no name found (but clean it better)
    if not metadata["name"]:
        # Clean filename and use as fallback - remove common resume keywords
        filename_clean = re.sub(r'[-_.]', ' ', filename_base).strip()
        # Remove common resume-related words
        filename_clean = re.sub(r'\b(resume|cv|curriculum|vitae|intern|internship|fresher|experienced|updated|final|latest)\b', '', filename_clean, flags=re.IGNORECASE)
        filename_clean = re.sub(r'\s+', ' ', filename_clean).strip()
        # Only use if it looks like a name (2-4 words, starts with capital)
        words = filename_clean.split()
        if 2 <= len(words) <= 4 and all(w[0].isupper() for w in words if w):
            metadata["name"] = filename_clean
        elif filename_clean:  # At least set something
            # Take first 2-3 capitalized words only
            name_words = [w for w in words if w and w[0].isupper() and w.isalpha()][:3]
            if name_words:
                metadata["name"] = ' '.join(name_words)
    
    # Extract skills (common tech keywords) - improved with word boundaries
    # Skills list with proper patterns for accurate matching
    skill_patterns = {
        'Python': [r'\bPython\b', r'\bPythonic\b'],
        'JavaScript': [r'\bJavaScript\b', r'\bJS\b', r'\bjs\b'],
        'Java': [r'\bJava\b'],  # Note: might match "JavaScript", so check JavaScript first
        'React': [r'\bReact\b', r'\bReact\.js\b'],
        'Node.js': [r'\bNode\.js\b', r'\bNodeJS\b', r'\bnodejs\b'],
        'Angular': [r'\bAngular\b', r'\bAngularJS\b'],
        'Vue': [r'\bVue\.js\b', r'\bVue\b'],
        'SQL': [r'\bSQL\b'],  # Check SQL separately, full DB names checked below
        'MongoDB': [r'\bMongoDB\b', r'\bMongo\b'],
        'PostgreSQL': [r'\bPostgreSQL\b', r'\bPostgres\b'],
        'MySQL': [r'\bMySQL\b'],
        'AWS': [r'\bAWS\b'],  # Check AWS separately, full name checked below
        'Docker': [r'\bDocker\b'],
        'Kubernetes': [r'\bKubernetes\b', r'\bK8s\b'],
        'Git': [r'\bGit\b', r'\bGitHub\b', r'\bGitLab\b'],  # Git might match GitHub/GitLab
        'Linux': [r'\bLinux\b'],
        'Django': [r'\bDjango\b'],
        'Flask': [r'\bFlask\b'],
        'Spring': [r'\bSpring\b', r'\bSpring Boot\b', r'\bSpring Framework\b'],
        'TypeScript': [r'\bTypeScript\b', r'\bTS\b'],
        'HTML': [r'\bHTML\b', r'\bHTML5\b'],
        'CSS': [r'\bCSS\b', r'\bCSS3\b'],
        'Machine Learning': [r'\bMachine Learning\b', r'\bML\b'],
        'Deep Learning': [r'\bDeep Learning\b', r'\bDL\b'],
        'TensorFlow': [r'\bTensorFlow\b'],
        'PyTorch': [r'\bPyTorch\b'],
        'C++': [r'\bC\+\+\b', r'\bCPP\b'],
        'C#': [r'\bC#\b', r'\bCSharp\b'],
        '.NET': [r'\b\.NET\b', r'\bDotNet\b', r'\bdotnet\b'],
        'PHP': [r'\bPHP\b'],
        'Ruby': [r'\bRuby\b', r'\bRuby on Rails\b'],
        'Go': [r'\bGo\b', r'\bGolang\b'],
        'Rust': [r'\bRust\b'],
        'Swift': [r'\bSwift\b'],
        'Kotlin': [r'\bKotlin\b']
    }
    
    # Add Amazon Web Services as a separate skill if needed
    skill_patterns['Amazon Web Services'] = [r'\bAmazon\s+Web\s+Services\b']
    
    # Skills that should be checked in order (longer names first to avoid partial matches)
    skill_order = [
        'Machine Learning', 'Deep Learning', 'Node.js', 'Angular', 'TypeScript',
        'PostgreSQL', 'MySQL', 'JavaScript', 'Kubernetes', 'TensorFlow',
        'Amazon Web Services', 'Spring Boot', 'Spring Framework', 'Ruby on Rails',
        'Vue.js', 'React.js', 'C++', 'C#', '.NET', 'CSS3', 'HTML5',
        'Python', 'React', 'Vue', 'Java', 'SQL', 'MongoDB', 'AWS', 'Docker',
        'GitHub', 'GitLab', 'Git', 'Linux', 'Django', 'Flask', 'Spring',
        'PyTorch', 'PHP', 'Ruby', 'Go', 'Rust', 'Swift', 'Kotlin',
        'HTML', 'CSS'
    ]
    
    found_skills = []
    text_lower = text.lower()
    
    # Track which parts of text have been matched to avoid double-counting
    matched_positions = set()
    
    # Check skills in order (longer/more specific first)
    for skill in skill_order:
        if skill in skill_patterns:
            patterns = skill_patterns[skill]
            for pattern in patterns:
                matches = list(re.finditer(pattern, text, re.IGNORECASE))
                for match in matches:
                    # Check if this position overlaps with a previous match
                    match_range = set(range(match.start(), match.end()))
                    if not matched_positions.intersection(match_range):
                        found_skills.append(skill)
                        matched_positions.update(match_range)
                        break  # Only add skill once even if multiple patterns match
                if skill in found_skills:
                    break
    
    metadata["skills"] = found_skills[:10]  # Limit to 10 skills
    
    # Extract years of experience from dates (WORK EXPERIENCE ONLY - excludes education)
    # Look for date patterns like "2015 - 2020", "Jan 2018 - Present", etc.
    # But only count dates that appear in work experience sections, not education
    
    date_patterns = [
        r'(\d{4})\s*[-–—]\s*(\d{4}|Present|Current|Now)',
        r'(\d{1,2}[/-]\d{4})\s*[-–—]\s*(\d{1,2}[/-]\d{4}|Present|Current|Now)',
        r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}\s*[-–—]\s*((Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}|Present|Current|Now)',
    ]
    
    # Keywords that indicate EDUCATION sections (exclude these dates)
    education_keywords = [
        'education', 'university', 'college', 'school', 'degree', 'bachelor', 'master', 
        'phd', 'doctorate', 'diploma', 'certificate', 'graduated', 'graduation', 
        'student', 'studied', 'coursework', 'gpa', 'major', 'minor', 'academic',
        'bachelor\'s', 'master\'s', 'associate\'s', 'bs ', 'ba ', 'ms ', 'mba',
        'b.sc', 'm.sc', 'b.eng', 'm.eng', 'undergraduate', 'graduate', 'thesis'
    ]
    
    # Keywords that indicate WORK EXPERIENCE sections (include these dates)
    work_keywords = [
        'experience', 'work', 'employment', 'position', 'role', 'job', 'career',
        'employed', 'worked', 'company', 'employer', 'organization', 'corporation',
        'engineer', 'developer', 'manager', 'analyst', 'consultant', 'specialist',
        'director', 'lead', 'senior', 'junior', 'associate', 'intern', 'internship',
        'responsibilities', 'achievements', 'projects', 'technologies', 'tools'
    ]
    
    years_found = []
    from datetime import datetime
    current_year = datetime.now().year
    
    # Split text into lines for better context detection
    lines = text.split('\n')
    
    for pattern in date_patterns:
        matches = re.finditer(pattern, text, re.IGNORECASE)
        for match in matches:
            start_date = match.group(1)
            end_date = match.group(2) if len(match.groups()) > 1 else None
            
            # Get context around the date match (100 characters before and after)
            match_start = match.start()
            match_end = match.end()
            context_start = max(0, match_start - 100)
            context_end = min(len(text), match_end + 100)
            context = text[context_start:context_end].lower()
            
            # Check if this date is in an education section
            is_education = any(keyword in context for keyword in education_keywords)
            
            # Check if this date is in a work experience section
            is_work = any(keyword in context for keyword in work_keywords)
            
            # Also check the line containing the date
            line_num = text[:match_start].count('\n')
            if line_num < len(lines):
                line_text = lines[line_num].lower()
                if any(keyword in line_text for keyword in education_keywords):
                    is_education = True
                if any(keyword in line_text for keyword in work_keywords):
                    is_work = True
            
            # Only count if it's work experience, not education
            # Skip if it's clearly education-related
            if is_education:
                continue  # Skip education dates
            
            # Include if it's clearly work-related OR if it's ambiguous (not clearly education)
            # This is more lenient - we only exclude dates that are clearly in education sections
            # This helps catch work experience even if work keywords aren't explicitly found nearby
            if is_work or not is_education:
                # Extract year from start date
                year_match = re.search(r'\d{4}', start_date)
                if year_match:
                    start_year = int(year_match.group())
                    # Additional validation: skip if start year is too old (likely education)
                    # Most work experience starts after age 18-22, so before 1990 might be education
                    # But be lenient - only skip if clearly unreasonable (before 1950)
                    if start_year < 1950:
                        continue
                    
                    if end_date and end_date.lower() not in ['present', 'current', 'now']:
                        end_year_match = re.search(r'\d{4}', end_date)
                        if end_year_match:
                            end_year = int(end_year_match.group())
                            # Validate: end year should be >= start year
                            if end_year >= start_year:
                                years_found.append(end_year - start_year)
                    else:
                        # Current position
                        years_found.append(current_year - start_year)
    
    if years_found:
        # Sum all years (could be multiple positions)
        total_years = sum(years_found)
        metadata["years_experience"] = min(total_years, 50)  # Cap at 50 years
    
    # Extract education level - improved with context checking
    # Education context keywords to ensure we're matching actual degrees
    education_context_keywords = [
        "degree", "education", "university", "college", "school", 
        "institute", "graduated", "graduation", "bachelor", "master",
        "phd", "doctorate", "diploma", "certification"
    ]
    
    # Check if text contains education-related context
    text_lower = text.lower()
    has_education_context = any(ctx in text_lower for ctx in education_context_keywords)
    
    # Education keywords - more specific patterns to avoid false positives
    education_keywords = {
        "PhD": [
            r'\bph\.?\s*d\.?\b',  # Ph.D or PhD
            r'\bdoctorate\b',
            r'\bdoctoral\s+degree\b',
            r'\bdoctor\s+of\s+philosophy\b'
        ],
        "Master's": [
            r'\bmaster\'?s?\s+degree\b',  # Master's degree or Masters degree
            r'\bm\.?\s*s\.?\b',  # M.S or MS
            r'\bm\.?\s*sc\.?\b',  # M.Sc
            r'\bm\.?\s*eng\.?\b',  # M.Eng
            r'\bmba\b',  # MBA
            r'\bma\b',  # MA (Master of Arts)
            r'\bmsc\b',  # MSc
            r'\bmeng\b'  # MEng
        ],
        "Bachelor's": [
            r'\bbachelor\'?s?\s+degree\b',  # Bachelor's degree or Bachelors degree
            r'\bb\.?\s*s\.?\b',  # B.S or BS
            r'\bb\.?\s*a\.?\b',  # B.A or BA
            r'\bb\.?\s*sc\.?\b',  # B.Sc
            r'\bb\.?\s*eng\.?\b',  # B.Eng
            r'\bbsc\b',  # BSc
            r'\bbeng\b',  # BEng
            r'\bbtech\b'  # BTech
        ],
        "Associate's": [
            r'\bassociate\'?s?\s+degree\b',
            r'\ba\.?\s*a\.?\b',  # A.A
            r'\ba\.?\s*s\.?\b',  # A.S
            r'\baas\b'  # AAS
        ],
        "Diploma": [
            r'\bdiploma\s+in\b',
            r'\bdiploma\s+from\b',
            r'\beducational\s+certificate\b',
            r'\bdegree\s+certificate\b'
        ]
    }
    
    # Find all education levels mentioned (prioritize highest degree)
    # More strict: abbreviations need education context nearby
    found_levels = []
    degree_order = ["PhD", "Master's", "Bachelor's", "Associate's", "Diploma"]
    
    # Patterns that require strict education context (abbreviations that can be ambiguous)
    strict_patterns = {
        "Master's": [r'\bm\.?\s*s\.?\b', r'\bm\.?\s*sc\.?\b', r'\bm\.?\s*eng\.?\b', r'\bma\b', r'\bmsc\b', r'\bmeng\b'],
        "Bachelor's": [r'\bb\.?\s*s\.?\b', r'\bb\.?\s*a\.?\b', r'\bb\.?\s*sc\.?\b', r'\bb\.?\s*eng\.?\b', r'\bbsc\b', r'\bbeng\b', r'\bbtech\b'],
        "Associate's": [r'\ba\.?\s*a\.?\b', r'\ba\.?\s*s\.?\b', r'\baas\b']
    }
    
    # Non-ambiguous patterns (full words that are clearly education-related)
    clear_patterns = {
        "PhD": [r'\bph\.?\s*d\.?\b', r'\bdoctorate\b', r'\bdoctoral\s+degree\b', r'\bdoctor\s+of\s+philosophy\b'],
        "Master's": [r'\bmaster\'?s?\s+degree\b', r'\bmba\b'],
        "Bachelor's": [r'\bbachelor\'?s?\s+degree\b'],
        "Associate's": [r'\bassociate\'?s?\s+degree\b'],
        "Diploma": [r'\bdiploma\s+in\b', r'\bdiploma\s+from\b', r'\beducational\s+certificate\b', r'\bdegree\s+certificate\b']
    }
    
    for level in degree_order:
        level_found = False
        
        # First check clear patterns (full words/obvious abbreviations like MBA)
        if level in clear_patterns:
            for pattern in clear_patterns[level]:
                if re.search(pattern, text, re.IGNORECASE):
                    matches = list(re.finditer(pattern, text, re.IGNORECASE))
                    for match in matches:
                        # For clear patterns, check broader context
                        start = max(0, match.start() - 150)
                        end = min(len(text), match.end() + 150)
                        context = text[start:end].lower()
                        
                        # Check if it's NOT in a clear non-education context
                        non_education_contexts = [
                            'microsoft', 'ms office', 'ms windows', 'ms excel', 'ms word',
                            'master of ceremonies', 'masters tournament', 'master craftsman',
                            'master class', 'master plan', 'master control'
                        ]
                        
                        is_non_education = any(non_ed in context for non_ed in non_education_contexts)
                        
                        if not is_non_education and (has_education_context or any(ctx in context for ctx in education_context_keywords)):
                            found_levels.append(level)
                            level_found = True
                            break
                    if level_found:
                        break
        
        # Then check strict patterns (abbreviations that need education context)
        if not level_found and level in strict_patterns:
            for pattern in strict_patterns[level]:
                if re.search(pattern, text, re.IGNORECASE):
                    matches = list(re.finditer(pattern, text, re.IGNORECASE))
                    for match in matches:
                        # For strict patterns, require education context within 50 chars
                        start = max(0, match.start() - 50)
                        end = min(len(text), match.end() + 50)
                        context = text[start:end].lower()
                        
                        # Require education context nearby for abbreviations
                        # Also exclude common false positives
                        non_education_contexts = [
                            'microsoft', 'ms office', 'ms windows', 'ms excel', 'ms word', 'ms teams',
                            'massachusetts', 'ma ',  # State abbreviation
                            'master of ceremonies', 'masters tournament',
                            'email', '@', 'gmail', 'yahoo',  # Email context
                            'company', 'corporation', 'inc', 'llc',  # Company context
                            'project manager', 'product manager', 'program manager'  # Job title context
                        ]
                        
                        # Check if it's in a non-education context
                        is_non_education = any(non_ed in context for non_ed in non_education_contexts)
                        
                        # Must have education context AND not be in non-education context
                        has_ed_context = any(ctx in context for ctx in education_context_keywords)
                        
                        if has_ed_context and not is_non_education:
                            found_levels.append(level)
                            level_found = True
                            break
                    if level_found:
                        break
        
        if level_found:
            break  # Stop after finding highest level
    
    # Set to highest degree found, or empty if none found
    if found_levels:
        # Get the first (highest) level found
        metadata["education_level"] = found_levels[0]
    else:
        # If no specific degree found, leave empty (will be shown as "Not Specified" in UI)
        metadata["education_level"] = ""
    
    # Extract job titles (common patterns) - improved with context validation
    job_title_patterns = [
        r'(Senior|Junior|Lead|Principal|Staff|Associate)?\s*(Software|Data|ML|AI|DevOps|Cloud|Full.?Stack|Front.?end|Back.?end|Mobile|QA|Test|Security|Network|System|Database|Business|Product|Project|Marketing|Sales|HR|Finance|Operations|Research|Design|UX|UI)\s+(Engineer|Developer|Architect|Analyst|Scientist|Manager|Specialist|Consultant|Designer|Director|Lead|Coordinator|Associate|Executive|Officer|Administrator|Technician)',
        r'(Software|Data|ML|AI|DevOps|Cloud|Full.?Stack|Front.?end|Back.?end|Mobile|QA|Test|Security|Network|System|Database|Business|Product|Project|Marketing|Sales|HR|Finance|Operations|Research|Design|UX|UI)\s+(Engineer|Developer|Architect|Analyst|Scientist|Manager|Specialist|Consultant|Designer|Director|Lead|Coordinator|Associate|Executive|Officer|Administrator|Technician)',
        r'(Programmer|Developer|Engineer|Analyst|Manager|Director|Consultant|Specialist|Designer|Architect|Scientist)',
    ]
    
    # Context keywords that suggest this is a job title (not other usage)
    job_context_keywords = [
        'position', 'role', 'title', 'worked as', 'served as', 'employed as',
        'experience', 'employment', 'career', 'responsibilities', 'at', 'company'
    ]
    
    # Patterns to exclude (common false positives)
    exclude_patterns = [
        r'project manager', r'program manager', r'product manager',  # Often matched incorrectly
        r'\bmanager\b.*\bmanager\b',  # Manager manager
    ]
    
    titles_found = []
    for pattern in job_title_patterns:
        matches = re.finditer(pattern, text, re.IGNORECASE)
        for match in matches:
            title = match.group(0).strip()
            
            # Basic validation
            if len(title) < 3 or len(title) > 50:
                continue
            
            # Check if it's in a valid job title context
            match_start = match.start()
            match_end = match.end()
            context_start = max(0, match_start - 100)
            context_end = min(len(text), match_end + 100)
            context = text[context_start:context_end].lower()
            
            # Skip if it's a false positive pattern
            if any(re.search(exclude_pattern, title, re.IGNORECASE) for exclude_pattern in exclude_patterns):
                continue
            
            # Prefer matches that are near job context keywords
            has_job_context = any(keyword in context for keyword in job_context_keywords)
            
            # Also check the line containing the match
            line_num = text[:match_start].count('\n')
            lines = text.split('\n')
            if line_num < len(lines):
                line_text = lines[line_num].lower()
                if any(keyword in line_text for keyword in job_context_keywords):
                    has_job_context = True
            
            # Include if it has job context OR if it's in a section that likely contains titles
            if has_job_context or any(keyword in context for keyword in ['experience', 'employment', 'work']):
                titles_found.append(title)
    
    # Remove duplicates and limit
    seen = set()
    unique_titles = []
    for title in titles_found:
        title_lower = title.lower().strip()
        # Skip if it's too generic or looks invalid
        if title_lower in ['manager', 'director', 'engineer', 'developer', 'analyst']:
            continue  # Too generic, need more context
        if title_lower not in seen:
            seen.add(title_lower)
            unique_titles.append(title)
            if len(unique_titles) >= 5:  # Limit to 5 most recent titles
                break
    
    metadata["job_titles"] = unique_titles
    
    # Extract company names (look for capitalized words after job titles or in experience section)
    # Improved with better context validation and more flexible patterns
    company_patterns = [
        r'at\s+([A-Z][a-zA-Z\s&\.\-]+?)(?:\s*\n|\s*-|\s*\||$)',  # "at Company\n" or "at Company -"
        r'(?:worked|working|employed)\s+(?:at|for|with)\s+([A-Z][a-zA-Z\s&\.\-]+?)(?:\s*\n|\s*-|\s*\||$)',
        r'([A-Z][a-zA-Z\s&\.\-]+?)\s*(?:Inc|LLC|Corp|Ltd|Company|Technologies|Systems|Solutions|Group|Industries|Pvt|Limited)\b',
        r'(?:^|\n)\s*([A-Z][a-zA-Z\s&\.\-]{3,40}?)\s*[\|\-]\s*(?:Software|Engineer|Developer|Analyst|Manager|Director)',
    ]
    
    # Words to exclude (common false positives)
    exclude_company_words = [
        'the', 'and', 'at', 'of', 'in', 'on', 'with', 'for', 'from', 'to',
        'resume', 'cv', 'curriculum', 'vitae', 'experience', 'education',
        'skills', 'projects', 'references', 'contact', 'email', 'phone'
    ]
    
    # Context keywords that suggest this is a company
    company_context_keywords = [
        'at', 'company', 'employer', 'organization', 'corporation', 'firm',
        'experience', 'employment', 'worked', 'employed'
    ]
    
    companies_found = []
    for pattern in company_patterns:
        matches = re.finditer(pattern, text)
        for match in matches:
            company = match.group(1).strip() if match.groups() else match.group(0).strip()
            
            # Clean up company name - remove trailing newlines, dates, etc.
            company = re.sub(r'\s*\n.*$', '', company)  # Remove everything after newline
            company = re.sub(r'\s*[\|\-]\s*\d{4}.*$', '', company)  # Remove dates
            company = re.sub(r'\s*\(.*?\)\s*', ' ', company)  # Remove parentheses content
            company = company.strip()
            
            # Basic validation
            if len(company) < 3 or len(company) > 50:
                continue
            
            # Skip if contains only common words
            if company.lower() in ['the', 'and', 'at', 'of', 'in', 'on', 'with']:
                continue
            
            # Check if it's in a valid company context
            match_start = match.start()
            match_end = match.end()
            context_start = max(0, match_start - 80)
            context_end = min(len(text), match_end + 80)
            context = text[context_start:context_end].lower()
            
            # Skip if it's in excluded words or common false positives
            company_words = company.split()
            if any(word.lower() in exclude_company_words for word in company_words):
                continue
            
            # Prefer matches near company context keywords
            has_company_context = any(keyword in context for keyword in company_context_keywords)
            
            # Also check the line containing the match
            line_num = text[:match_start].count('\n')
            lines = text.split('\n')
            if line_num < len(lines):
                line_text = lines[line_num].lower()
                if any(keyword in line_text for keyword in company_context_keywords):
                    has_company_context = True
            
            # Include if it has company context OR appears in experience section
            if has_company_context or any(keyword in context for keyword in ['experience', 'employment', 'work']):
                # Additional check: company should start with capital and have reasonable structure
                if company and company[0].isupper() and not company.lower().startswith(tuple(exclude_company_words)):
                    companies_found.append(company)
    
    # Remove duplicates and filter out invalid entries
    seen = set()
    unique_companies = []
    for company in companies_found:
        company_lower = company.lower().strip()
        # Skip if it's too generic or already seen
        if company_lower in seen or company_lower in exclude_company_words:
            continue
        # Skip single words that are too common
        if len(company.split()) == 1 and company_lower in ['company', 'inc', 'llc', 'corp']:
            continue
        seen.add(company_lower)
        unique_companies.append(company)
        if len(unique_companies) >= 5:
            break
    
    metadata["companies"] = unique_companies
    
    # Extract location (improved - looks for city, state patterns with context validation)
    # Exclude programming languages and common tech terms from location detection
    tech_terms = [
        'Python', 'Java', 'JavaScript', 'TypeScript', 'Ruby', 'PHP', 'Swift', 'Kotlin',
        'React', 'Angular', 'Vue', 'Node', 'Django', 'Flask', 'Spring', 'Express',
        'SQL', 'MySQL', 'PostgreSQL', 'MongoDB', 'Redis', 'Docker', 'Kubernetes',
        'AWS', 'Azure', 'GCP', 'Git', 'GitHub', 'Linux', 'Windows', 'Script', 'Code'
    ]
    
    location_patterns = [
        r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*),\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)',  # City, Country/State (full name)
        r'([A-Z][a-z]+),\s*([A-Z]{2})\b',  # City, State (2-letter code)
    ]
    
    # Only search in first 1000 characters (header/contact section)
    text_header = text[:1000]
    
    for pattern in location_patterns:
        matches = re.finditer(pattern, text_header)
        for match in matches:
            location_candidate = match.group(0).strip()
            city_part = match.group(1).strip()
            
            # Skip if the city part matches a tech term
            if city_part in tech_terms or city_part.upper() in tech_terms:
                continue
            
            # Skip if surrounded by tech context
            context_start = max(0, match.start() - 50)
            context_end = min(len(text_header), match.end() + 50)
            context = text_header[context_start:context_end].lower()
            
            tech_context_words = ['programming', 'language', 'framework', 'library', 'skill', 'proficient', 'experience with']
            if any(word in context for word in tech_context_words):
                continue
            
            metadata["location"] = location_candidate
            break
        
        if metadata["location"]:
            break
    
    # Extract certifications - improved with comprehensive patterns and generic detection
    cert_patterns = {
        # AWS certifications - expanded patterns
        "AWS Certified": [
            r'\bAWS\s+Certified\b', r'\bAmazon\s+Web\s+Services\s+Certified\b',
            r'\bAWS\s+Solutions\s+Architect\b', r'\bAWS\s+Developer\b', r'\bAWS\s+SysOps\b',
            r'\bAWS\s+SA\b', r'\bAWS\s+CLF\b', r'\bAWS\s+SAA\b', r'\bAWS\s+DVA\b', r'\bAWS\s+SOA\b'
        ],
        # Azure certifications - expanded patterns
        "Azure Certified": [
            r'\bAzure\s+Certified\b', r'\bMicrosoft\s+Azure\b', r'\bAzure\s+AZ-\d+\b',
            r'\bAZ-900\b', r'\bAZ-104\b', r'\bAZ-305\b', r'\bAZ-204\b', r'\bAZ-400\b',
            r'\bAzure\s+Fundamentals\b', r'\bAzure\s+Administrator\b', r'\bAzure\s+Architect\b',
            r'\bAzure\s+Developer\b', r'\bAzure\s+DevOps\b'
        ],
        # Google certifications - comprehensive
        "Google Cloud Certified": [
            r'\bGCP\s+Certified\b', r'\bGoogle\s+Cloud\s+Certified\b',
            r'\bGCP\s+Architect\b', r'\bGCP\s+Developer\b', r'\bGCP\s+Data\s+Engineer\b',
            r'\bGoogle\s+Cloud\s+Professional\b', r'\bGoogle\s+Cloud\s+Associate\b',
            r'\bGCP\s+Professional\b', r'\bProfessional\s+Cloud\s+Architect\b',
            r'\bProfessional\s+Cloud\s+Developer\b', r'\bProfessional\s+Data\s+Engineer\b'
        ],
        "Google Analytics": [r'\bGoogle\s+Analytics\s+Certified\b', r'\bGA\s+Certified\b', r'\bGAIQ\b'],
        "Google Ads": [r'\bGoogle\s+Ads\s+Certified\b', r'\bGoogle\s+AdWords\s+Certified\b'],
        "Google IT Support": [r'\bGoogle\s+IT\s+Support\b', r'\bGoogle\s+IT\s+Certificate\b'],
        "Google Data Analytics": [r'\bGoogle\s+Data\s+Analytics\b'],
        "Google UX Design": [r'\bGoogle\s+UX\s+Design\b'],
        "Google Project Management": [r'\bGoogle\s+Project\s+Management\b'],
        "Google Cybersecurity": [r'\bGoogle\s+Cybersecurity\b'],
        # Project Management
        "PMP": [r'\bPMP\b', r'\bProject\s+Management\s+Professional\b'],
        "PRINCE2": [r'\bPRINCE2\b'],
        "CAPM": [r'\bCAPM\b'],
        # Agile/Scrum
        "Scrum Master": [r'\bScrum\s+Master\b', r'\bCSM\b', r'\bCertified\s+Scrum\s+Master\b'],
        "Scrum Product Owner": [r'\bCSPO\b', r'\bCertified\s+Scrum\s+Product\s+Owner\b'],
        "SAFe": [r'\bSAFe\b', r'\bScaled\s+Agile\b'],
        "Agile": [r'\bAgile\s+Certified\b', r'\bPMI-ACP\b'],
        # ITIL
        "ITIL": [r'\bITIL\b', r'\bITIL\s+Foundation\b', r'\bITIL\s+v4\b'],
        # Security certifications
        "CISSP": [r'\bCISSP\b', r'\bCertified\s+Information\s+Systems\s+Security\s+Professional\b'],
        "Security+": [r'\bSecurity\+\b', r'\bSecurity Plus\b', r'\bCompTIA\s+Security\+\b'],
        "CEH": [r'\bCEH\b', r'\bCertified\s+Ethical\s+Hacker\b'],
        "CISM": [r'\bCISM\b', r'\bCertified\s+Information\s+Security\s+Manager\b'],
        "CISA": [r'\bCISA\b', r'\bCertified\s+Information\s+Systems\s+Auditor\b'],
        # Vendor certifications
        "Oracle Certified": [r'\bOracle\s+Certified\b', r'\bOCA\b', r'\bOCP\b', r'\bOCE\b'],
        "Microsoft Certified": [
            r'\bMicrosoft\s+Certified\b', r'\bMCSA\b', r'\bMCSE\b', r'\bMCSD\b',
            r'\bMicrosoft\s+Azure\b', r'\bMS-\d+\b'
        ],
        "Cisco Certified": [
            r'\bCisco\s+Certified\b', r'\bCCNA\b', r'\bCCNP\b', r'\bCCIE\b',
            r'\bCisco\s+CCNA\b', r'\bCisco\s+CCNP\b'
        ],
        # Cloud/DevOps
        "Kubernetes Certified": [r'\bCKA\b', r'\bCKAD\b', r'\bKubernetes\s+Certified\b'],
        "Docker Certified": [r'\bDocker\s+Certified\b'],
        "Terraform Certified": [r'\bTerraform\s+Certified\b', r'\bHashicorp\s+Terraform\b'],
        # Salesforce
        "Salesforce Certified": [
            r'\bSalesforce\s+Certified\b', r'\bSalesforce\s+Admin\b',
            r'\bSalesforce\s+Developer\b', r'\bSFDC\b'
        ],
        # Red Hat
        "Red Hat Certified": [r'\bRHCE\b', r'\bRHCSA\b', r'\bRed\s+Hat\b'],
        # CompTIA
        "CompTIA A+": [r'\bCompTIA\s+A\+\b', r'\bA\+\b'],
        "CompTIA Network+": [r'\bCompTIA\s+Network\+\b', r'\bNetwork\+\b'],
        "CompTIA Security+": [r'\bCompTIA\s+Security\+\b'],
        # IBM certifications - comprehensive
        "IBM Certified": [
            r'\bIBM\s+Certified\b', r'\bIBM\s+Professional\b',
            r'\bIBM\s+Specialist\b', r'\bIBM\s+Associate\b'
        ],
        "IBM Cloud": [
            r'\bIBM\s+Cloud\s+Certified\b', r'\bIBM\s+Cloud\s+Professional\b',
            r'\bIBM\s+Cloud\s+Solutions\s+Architect\b'
        ],
        "IBM Data Science": [
            r'\bIBM\s+Data\s+Science\s+Certified\b', r'\bIBM\s+Data\s+Science\s+Professional\b',
            r'\bIBM\s+Data\s+Analyst\b', r'\bIBM\s+Data\s+Engineer\b'
        ],
        "IBM AI Engineering": [
            r'\bIBM\s+AI\s+Engineering\b', r'\bIBM\s+Machine\s+Learning\b',
            r'\bIBM\s+Artificial\s+Intelligence\b'
        ],
        "IBM Watson": [r'\bIBM\s+Watson\s+Certified\b', r'\bWatson\s+Certified\b'],
        "IBM Power Systems": [r'\bIBM\s+Power\s+Systems\b'],
        "IBM DB2": [r'\bIBM\s+DB2\b', r'\bDB2\s+Certified\b'],
        "IBM Cognos": [r'\bIBM\s+Cognos\b', r'\bCognos\s+Certified\b'],
        "IBM Rational": [r'\bIBM\s+Rational\b'],
        # Data/ML
        "Tableau Certified": [r'\bTableau\s+Certified\b'],
        "Snowflake Certified": [r'\bSnowflake\s+Certified\b'],
        # Online Learning Platforms
        "Coursera": [r'\bCoursera\b', r'\bCoursera\s+Certificate\b', r'\bCoursera\s+Specialization\b'],
        "Udemy": [r'\bUdemy\b', r'\bUdemy\s+Certificate\b'],
        "edX": [r'\bedX\b', r'\bedX\s+Certificate\b'],
        "LinkedIn Learning": [r'\bLinkedIn\s+Learning\b', r'\bLynda\b'],
        "Pluralsight": [r'\bPluralsight\b'],
        "DataCamp": [r'\bDataCamp\b'],
        "Udacity": [r'\bUdacity\b', r'\bUdacity\s+Nanodegree\b'],
        # Platform-specific
        "HackerRank": [r'\bHackerRank\b', r'\bHackerRank\s+Certificate\b'],
        "Postman": [r'\bPostman\s+API\b', r'\bPostman\s+Student\s+Expert\b', r'\bAPI\s+Fundamentals\s+Student\s+Expert\b'],
        "MongoDB University": [r'\bMongoDB\s+University\b', r'\bMongoDB\s+Certified\b'],
        "Meta": [r'\bMeta\s+Certified\b', r'\bFacebook\s+Certified\b', r'\bMeta\s+Front-End\b', r'\bMeta\s+Back-End\b'],
        "freeCodeCamp": [r'\bfreeCodeCamp\b', r'\bFree\s+Code\s+Camp\b'],
        # Programming Language Certifications
        "Python Institute": [r'\bPCEP\b', r'\bPCAP\b', r'\bPCPP\b', r'\bPython\s+Institute\b'],
        "Java Certified": [r'\bOCJP\b', r'\bOCPJP\b', r'\bJava\s+SE\s+Programmer\b'],
        # Other common certifications
        "TOGAF": [r'\bTOGAF\b'],
        "COBIT": [r'\bCOBIT\b'],
        "Six Sigma": [r'\bSix\s+Sigma\b', r'\bLean\s+Six\s+Sigma\b', r'\bGreen\s+Belt\b', r'\bBlack\s+Belt\b']
    }
    
    certs_found = []
    seen_certs = set()
    
    # First, check for specific certification patterns
    for cert_name, patterns in cert_patterns.items():
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                matches = list(re.finditer(pattern, text, re.IGNORECASE))
                for match in matches:
                    context_start = max(0, match.start() - 80)
                    context_end = min(len(text), match.end() + 80)
                    context = text[context_start:context_end].lower()
                    
                    # Check if it's in a certifications section
                    line_num = text[:match.start()].count('\n')
                    lines = text.split('\n')
                    
                    # Check nearby lines for certification context
                    has_cert_context = False
                    for i in range(max(0, line_num - 3), min(len(lines), line_num + 3)):
                        line_lower = lines[i].lower()
                        if any(keyword in line_lower for keyword in [
                            'certification', 'certified', 'certificate', 'credential',
                            'license', 'cert', 'qualification'
                        ]):
                            has_cert_context = True
                            break
                    
                    # More lenient: include if in cert context OR if it's a known cert abbreviation
                    is_known_abbreviation = any(abbr in pattern for abbr in [
                        'PMP', 'CISSP', 'CEH', 'CISM', 'ITIL', 'CCNA', 'CCNP', 
                        'AZ-', 'AWS', 'CSM', 'CKA', 'CKAD', 'IBM', 'GCP', 'GA',
                        'Google'
                    ])
                    
                    # Skip only if clearly NOT about certification (skill mention)
                    if not has_cert_context and not is_known_abbreviation:
                        if any(word in context for word in [
                            'experience with', 'proficient in', 'expert in',
                            'skill in', 'knowledge of'
                        ]):
                            continue  # Likely a skill mention, not certification
                    
                    cert_lower = cert_name.lower()
                    if cert_lower not in seen_certs:
                        certs_found.append(cert_name)
                        seen_certs.add(cert_lower)
                    break
                if cert_name in certs_found:
                    break
    
    # Second, try to find generic certificates in a "Certifications" section
    # Look for lines that might contain certifications
    cert_keywords = ['certification', 'certificate', 'certified', 'credential', 'license']
    lines = text.split('\n')
    in_cert_section = False
    
    for i, line in enumerate(lines):
        line_lower = line.lower().strip()
        
        # Check if we're entering a certifications section
        if any(keyword in line_lower for keyword in cert_keywords):
            in_cert_section = True
            continue
        
        # If we're in a cert section, look for certificate-like patterns
        if in_cert_section and len(line.strip()) > 3:
            # Look for patterns like "Name - Issuer" or "Name (Issuer)"
            # Or just capitalized words that might be certifications
            cert_line_pattern = r'\b([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*(?:\s+\+)?)\b'
            potential_certs = re.findall(cert_line_pattern, line)
            
            for potential_cert in potential_certs:
                cert_clean = potential_cert.strip()
                # Skip common false positives
                if cert_clean.lower() in [
                    'certification', 'certified', 'certificate', 'credentials',
                    'experience', 'education', 'skills', 'projects', 'summary',
                    'resume', 'cv', 'name', 'address', 'phone', 'email'
                ]:
                    continue
                
                # Skip if it's too short or too long
                if len(cert_clean) < 3 or len(cert_clean) > 50:
                    continue
                
                # Check if it looks like a certification (has numbers, hyphens, or known cert keywords)
                if re.search(r'[A-Z]{2,}-?\d+|[A-Z]+\+', cert_clean) or any(keyword in cert_clean.lower() for keyword in [
                    'certified', 'professional', 'specialist', 'expert', 'foundation'
                ]):
                    cert_lower = cert_clean.lower()
                    if cert_lower not in seen_certs and len(certs_found) < 10:
                        certs_found.append(cert_clean)
                        seen_certs.add(cert_lower)
        
        # Reset if we hit another section
        if in_cert_section and line_lower in ['experience', 'education', 'skills', 'projects', 'summary']:
            in_cert_section = False
    
    metadata["certifications"] = certs_found[:15]  # Increased limit to 15
    
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
    
    openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()
    azure_key = os.getenv("AZURE_OPENAI_KEY", "").strip()
    azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
    # Use separate embedding deployment (different from chat model)
    azure_embedding_deployment = os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "").strip()
    azure_api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2025-01-01-preview").strip()
    
    # Remove trailing slash from endpoint if present
    if azure_endpoint and azure_endpoint.endswith('/'):
        azure_endpoint = azure_endpoint.rstrip('/')
    
    # Try Azure OpenAI embeddings ONLY if separate embedding deployment is configured
    # Note: Chat models (like gpt-4.1) cannot be used for embeddings
    if (embedding_provider == "azure_openai" or azure_key) and azure_endpoint and azure_embedding_deployment:
        try:
            from langchain_openai import AzureOpenAIEmbeddings
            logger.info(f"Using Azure OpenAI embeddings: {azure_embedding_deployment} at {azure_endpoint}")
            return AzureOpenAIEmbeddings(
                azure_deployment=azure_embedding_deployment,
                azure_endpoint=azure_endpoint,
                api_key=azure_key,
                api_version=azure_api_version
            )
        except Exception as e:
            logger.warning(f"Failed to initialize Azure OpenAI embeddings: {e}, falling back to local")
    elif azure_key and azure_endpoint and not azure_embedding_deployment:
        # Azure key exists but no embedding deployment - use local embeddings
        logger.info("Azure OpenAI key found but no embedding deployment configured. Using local HuggingFace embeddings.")
    
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
    azure_key = os.getenv("AZURE_OPENAI_KEY", "").strip()
    azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
    azure_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "").strip()
    azure_api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2025-01-01-preview").strip()
    
    # Remove trailing slash from endpoint if present
    if azure_endpoint and azure_endpoint.endswith('/'):
        azure_endpoint = azure_endpoint.rstrip('/')
    
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
                logger.error(f"Azure Key present: {bool(azure_key)}, Endpoint: {azure_endpoint}, Deployment: {azure_deployment}")
    
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


# 📅 How Experience Years Are Determined

This document explains how the system extracts and calculates years of experience from resumes.

## 🔍 Step 1: Date Pattern Detection (Work Experience Only)

The system searches for **date ranges** in the resume text using regex patterns. It looks for common employment date formats, but **ONLY counts work experience dates, NOT education dates**.

### Supported Date Formats:

1. **Year ranges:**
   - `2015 - 2020`
   - `2018 – 2024` (en dash)
   - `2020 — 2023` (em dash)

2. **Month/Year ranges:**
   - `01/2015 - 12/2020`
   - `Jan 2018 - Dec 2024`
   - `January 2018 - Present`

3. **Current positions:**
   - `2015 - Present`
   - `2018 - Current`
   - `2020 - Now`

### Regex Patterns Used:

```python
# Pattern 1: Year ranges
r'(\d{4})\s*[-–—]\s*(\d{4}|Present|Current|Now)'
# Matches: "2015 - 2020", "2018 – Present"

# Pattern 2: Month/Year ranges
r'(\d{1,2}[/-]\d{4})\s*[-–—]\s*(\d{1,2}[/-]\d{4}|Present|Current|Now)'
# Matches: "01/2015 - 12/2020", "6/2018 - Present"

# Pattern 3: Month name ranges
r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}\s*[-–—]\s*((Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}|Present|Current|Now)'
# Matches: "Jan 2018 - Dec 2024", "January 2015 - Present"
```

---

## 🔍 Step 1.5: Filter Education Dates

**IMPORTANT:** The system now distinguishes between work experience and education dates:

### Education Keywords (Excluded):
- `education`, `university`, `college`, `school`, `degree`, `bachelor`, `master`, `phd`, `doctorate`, `diploma`, `certificate`, `graduated`, `graduation`, `student`, `studied`, `coursework`, `gpa`, `major`, `minor`, `academic`, etc.

### Work Experience Keywords (Included):
- `experience`, `work`, `employment`, `position`, `role`, `job`, `career`, `employed`, `worked`, `company`, `employer`, `engineer`, `developer`, `manager`, etc.

**How it works:**
1. For each date range found, the system checks the **context** (100 characters before and after the date)
2. If the context contains **education keywords**, the date is **excluded**
3. If the context contains **work keywords**, the date is **included**
4. If ambiguous (neither clearly work nor education), the date is **excluded** to be safe

**Example:**
- ✅ **Counted:** "Software Engineer | Company ABC | 2015 - 2020" (work keywords present)
- ❌ **Not Counted:** "Bachelor's Degree | University XYZ | 2011 - 2015" (education keywords present)

---

## 🧮 Step 2: Calculate Years for Each Position

For each **work experience** date range found, the system calculates the duration:

### For Past Positions:
```
Years = End Year - Start Year

Example:
- Start: 2015
- End: 2020
- Years: 2020 - 2015 = 5 years
```

### For Current Positions:
```
Years = Current Year - Start Year

Example (if current year is 2024):
- Start: 2018
- End: Present
- Years: 2024 - 2018 = 6 years
```

### Code Implementation:

```python
from datetime import datetime
current_year = datetime.now().year

for match in date_patterns:
    start_date = match.group(1)  # e.g., "2015"
    end_date = match.group(2)     # e.g., "2020" or "Present"
    
    # Extract year from start date
    start_year = int(extract_year(start_date))  # e.g., 2015
    
    if end_date.lower() in ['present', 'current', 'now']:
        # Current position
        years = current_year - start_year
    else:
        # Past position
        end_year = int(extract_year(end_date))
        years = end_year - start_year
    
    years_found.append(years)
```

---

## ➕ Step 3: Sum All Positions

The system **sums all years** from multiple positions to get total experience:

### Example Resume:

```
Work Experience:
- Software Engineer at Company A: 2015 - 2018 (3 years) ✅ Counted
- Senior Engineer at Company B: 2018 - 2022 (4 years) ✅ Counted
- Lead Engineer at Company C: 2022 - Present (2 years, as of 2024) ✅ Counted

Education:
- Bachelor's Degree | University XYZ | 2011 - 2015 ❌ NOT Counted

Total Experience = 3 + 4 + 2 = 9 years (education years excluded)
```

### Code Implementation:

```python
if years_found:
    # Sum all years (could be multiple positions)
    total_years = sum(years_found)
    metadata["years_experience"] = min(total_years, 50)  # Cap at 50 years
```

**Note:** Experience is capped at **50 years** to prevent calculation errors.

---

## 📊 Step 4: Categorize Experience Levels

Once total years are calculated, candidates are categorized:

| Category | Years Range | Description |
|----------|-------------|-------------|
| 🟢 **Entry** | 0-2 years | Junior/Entry level positions |
| 🟡 **Mid** | 3-5 years | Mid-level professionals |
| 🟠 **Senior** | 6-10 years | Senior professionals |
| 🔴 **Expert** | 10+ years | Expert/Principal level |

### Code Implementation:

```python
entry_level = sum(1 for y in experience_data if 0 < y <= 2)
mid_level = sum(1 for y in experience_data if 2 < y <= 5)
senior_level = sum(1 for y in experience_data if 5 < y <= 10)
expert_level = sum(1 for y in experience_data if y > 10)
```

---

## 📈 Step 5: Calculate Statistics

### Average Experience:

```python
avg_exp = sum(experience_data) / len(experience_data)
```

**Example:**
- Candidate 1: 1 year
- Candidate 2: 16 years
- Average: (1 + 16) / 2 = **8.5 years**

### Distribution Histogram:

The system creates a histogram showing:
- **X-axis:** Years of experience (binned into ranges)
- **Y-axis:** Number of candidates in each bin
- **Bins:** 10 bins by default

---

## 🎯 Real Example from Your Dashboard

Based on your screenshot showing:
- **Entry (0-2 yrs):** 1 candidate
- **Expert (10+ yrs):** 1 candidate (16-17 years)
- **Average:** 9.0 years

### How This Was Calculated:

**Candidate 1:**
- Resume shows: "2023 - Present" (1 year as of 2024)
- **Category:** Entry (0-2 yrs) ✅

**Candidate 2:**
- Resume shows multiple positions:
  - Position 1: 2008 - 2015 (7 years)
  - Position 2: 2015 - 2024 (9 years)
  - Total: 7 + 9 = 16 years
- **Category:** Expert (10+ yrs) ✅

**Average:**
- (1 + 16) / 2 = **8.5 years** (rounded to 9.0)

---

## ⚠️ Limitations & Edge Cases

### 1. **Education vs Work Distinction:**
- The system uses keyword matching to distinguish education from work experience
- If a date appears in ambiguous context (neither clearly work nor education), it's excluded
- Very old dates (before 1950) are automatically excluded as likely education

### 2. **Overlapping Dates:**
If a resume shows overlapping employment periods, the system may overcount:
```
- Job 1: 2015 - 2020
- Job 2: 2018 - 2024  (overlaps with Job 1)
```
**Result:** System counts both, potentially inflating total years.

### 3. **Missing Dates:**
If dates are not in standard formats, they may not be detected:
```
- "Worked for 5 years" (not detected)
- "2015 to 2020" (may not match if "to" is used instead of "-")
```

### 4. **Part-time/Contract Work:**
The system doesn't distinguish between full-time and part-time positions.

### 5. **Gaps in Employment:**
Gaps are not considered - only total years worked.

### 6. **Internships:**
Internships are counted the same as full-time positions.

---

## 🔧 How to Improve Accuracy

### For Better Results:

1. **Use standard date formats:**
   - ✅ `2015 - 2020`
   - ✅ `Jan 2018 - Present`
   - ❌ `2015 to 2020` (may not match)
   - ❌ `Five years` (won't match)

2. **List all positions:**
   - Include start and end dates for each role
   - Use consistent date format throughout

3. **Mark current positions:**
   - Use "Present", "Current", or "Now" for ongoing roles

---

## 📍 Code Locations

### Experience Extraction:
- **File:** `utils.py`
- **Function:** `extract_metadata()`
- **Lines:** 247-280

### Experience Visualization:
- **File:** `app.py`
- **Function:** `show_analytics()`
- **Lines:** 658-700

---

## 🧪 Testing the Calculation

You can test by creating a resume with:

```
Work Experience:
Software Engineer | Company A | 2015 - 2018
Senior Engineer | Company B | 2018 - 2022
Lead Engineer | Company C | 2022 - Present

Education:
Bachelor's Degree | University XYZ | 2011 - 2015
```

**Expected Result:**
- Position 1: 3 years (2018 - 2015) ✅ Work experience
- Position 2: 4 years (2022 - 2018) ✅ Work experience
- Position 3: 2 years (2024 - 2022, if current year is 2024) ✅ Work experience
- Education: 4 years (2011 - 2015) ❌ NOT counted
- **Total: 9 years** (only work experience)
- **Category: Senior (6-10 years)**

---

## 💡 Future Improvements

Potential enhancements:
- Better handling of overlapping dates
- Detection of part-time vs. full-time
- Consider employment gaps
- Support for more date formats
- NLP-based date extraction for non-standard formats


# 📊 Scoring System Explanation

This document explains how the candidate scoring and ranking system works in the Resume RAG application.

## 🎯 Three Types of Scores

The system uses **three different scoring methods** for different purposes:

---

## 1. **Completeness Score (0-4 points)** 
**Used in:** Candidate Profile Completeness section

Simple scoring based on basic profile information:

| Criteria | Points | Description |
|----------|--------|-------------|
| ✅ Valid Name | 1 point | Name is extracted and valid (not a header like "RESUME" or "CV") |
| ✅ Email | 1 point | Email address is found |
| ✅ Phone | 1 point | Phone number is found |
| ✅ Skills | 1 point | At least one skill is detected |

**Maximum Score:** 4 points (100% complete profile)

**Example:**
- Candidate with name, email, phone, and skills = **4/4** ✅
- Candidate with only name and email = **2/4** (50%)

---

## 2. **Fit Score (0-100 points)**
**Used in:** Candidate Ranking & Fit Score section (ATS-Style)

Comprehensive scoring system similar to Applicant Tracking Systems (ATS):

### Scoring Breakdown:

| Category | Points | Calculation |
|----------|--------|--------------|
| **Name** | 10 points | Valid name found = 10 points, Invalid/Missing = 0 |
| **Contact Info** | 20 points | Email (10) + Phone (10) |
| **Skills** | 20 points | 2 points per skill, maximum 20 points (10+ skills) |
| **Experience** | 25 points | 2.5 points per year, maximum 25 points (10+ years) |
| **Education** | 15 points | Education level found = 15 points |
| **Certifications** | 10 points | 2 points per certification, maximum 10 points (5+ certs) |

**Maximum Score:** 100 points

### Detailed Calculation:

```python
# Example: Candidate with:
# - Valid name: "John Doe" → +10 points
# - Email: "john@email.com" → +10 points
# - Phone: "123-456-7890" → +10 points
# - 8 skills → 8 × 2 = 16 points (max 20)
# - 5 years experience → 5 × 2.5 = 12.5 points (max 25)
# - Bachelor's degree → +15 points
# - 2 certifications → 2 × 2 = 4 points (max 10)

Total Fit Score = 10 + 10 + 10 + 16 + 12.5 + 15 + 4 = 77.5/100
```

### Score Interpretation:

- **90-100:** Excellent candidate (complete profile, high experience)
- **75-89:** Very good candidate
- **60-74:** Good candidate
- **40-59:** Average candidate
- **0-39:** Incomplete profile

---

## 3. **Rank Score (Relevance Score)**
**Used in:** Filter ranking when "Rank by relevance" is enabled

Dynamic scoring based on how well a candidate matches a search query:

### Scoring Breakdown:

| Match Type | Points | Description |
|------------|--------|-------------|
| **Name Match** | 10.0 points | Query text found in candidate name |
| **Email Match** | 5.0 points | Query text found in email |
| **Skills Match** | 3.0 points per match | Each matching skill adds 3 points |
| **Completeness Bonus** | 0-3.5 points | Bonus for having complete metadata |

### Completeness Bonus Details:

- Name present: +1.0
- Email present: +1.0
- Phone present: +1.0
- Skills present: +0.2 per skill (up to 5 skills = +1.0)

**Maximum Bonus:** 3.5 points

### Example Calculation:

**Query:** "Python developer"

**Candidate A:**
- Name: "John Python" → +10.0 (name match)
- Skills: ["Python", "Django", "React"] → +3.0 (Python match)
- Has name, email, phone, 3 skills → +3.0 (completeness)
- **Total Rank Score: 16.0**

**Candidate B:**
- Skills: ["Python", "Flask"] → +3.0 (Python match)
- Has name, email → +2.0 (completeness)
- **Total Rank Score: 5.0**

**Result:** Candidate A ranks higher (16.0 > 5.0)

---

## 🔍 How Experience Years Are Calculated

The system extracts years of experience from resume dates:

1. **Searches for date patterns:**
   - "2015 - 2020"
   - "Jan 2018 - Present"
   - "01/2015 - 12/2020"

2. **Calculates duration:**
   - For past positions: End Year - Start Year
   - For current positions: Current Year - Start Year

3. **Sums all positions:**
   - If candidate worked 2015-2018 (3 years) and 2019-2024 (5 years)
   - Total experience = 3 + 5 = **8 years**

4. **Capped at 50 years** (to prevent errors)

---

## 📈 How Skills Are Detected

The system searches for common technical skills in resume text:

**Supported Skills Include:**
- Programming: Python, JavaScript, Java, C++, C#, Go, Rust, etc.
- Frameworks: React, Angular, Vue, Django, Flask, Spring, etc.
- Databases: SQL, MongoDB, PostgreSQL, etc.
- Cloud: AWS, Docker, Kubernetes, Azure, etc.
- ML/AI: Machine Learning, Deep Learning, TensorFlow, PyTorch, etc.

**Detection Method:**
- Case-insensitive text matching
- Limited to top 10 skills per candidate
- Skills must appear in resume text

---

## 🎓 How Education Level Is Detected

The system searches for education keywords:

| Level | Keywords Detected |
|-------|-------------------|
| **PhD** | "phd", "ph.d", "doctorate", "doctoral" |
| **Master's** | "master", "ms", "m.s", "mba", "m.sc", "meng" |
| **Bachelor's** | "bachelor", "bs", "b.s", "ba", "b.a", "bsc", "b.sc", "beng" |
| **Associate's** | "associate", "aa", "a.a", "as", "a.s" |
| **Diploma** | "diploma", "certificate" |

**Note:** System takes the **highest level** found (PhD > Master's > Bachelor's, etc.)

---

## 🏆 How Certifications Are Detected

The system searches for common certification keywords:

**Supported Certifications:**
- **Cloud:** AWS Certified, Azure, GCP, Google Cloud
- **Project Management:** PMP, Scrum Master, Agile, ITIL
- **Security:** CISSP, Security+, CEH, CISM
- **Vendor:** Oracle Certified, Microsoft Certified, Cisco
- **DevOps:** Kubernetes, Docker, Terraform

**Detection:** Case-insensitive text matching in resume

---

## 💡 Tips for Better Scores

### To Improve Fit Score:

1. **Include complete contact info** (name, email, phone) = +30 points
2. **List multiple skills** (10+ skills = max 20 points)
3. **Show years of experience** (10+ years = max 25 points)
4. **Include education level** = +15 points
5. **List certifications** (5+ certs = max 10 points)

### To Improve Rank Score (when filtering):

1. **Use specific keywords** that match candidate skills
2. **Include candidate name** in search query for name matching
3. **Complete profiles** get bonus points

---

## 🔧 Technical Implementation

### Fit Score Calculation:
```python
# Location: app.py, show_analytics() function
# Lines: 859-937

score = 0
# Name validation and scoring
# Contact info scoring
# Skills counting and scoring
# Experience calculation
# Education detection
# Certification counting
```

### Rank Score Calculation:
```python
# Location: utils.py, rank_candidates() function
# Lines: 619-676

# Query-based relevance scoring
# Name/email/skills matching
# Completeness bonus
```

---

## 📊 Score Display

- **Completeness Score:** Shown as X/4 in completeness chart
- **Fit Score:** Shown as X/100 in ranking chart (color-coded: red → yellow → green)
- **Rank Score:** Used internally for sorting when filtering

---

## 🎯 Use Cases

1. **Completeness Score:** Quick check if resume has basic information
2. **Fit Score:** Overall candidate quality assessment (like ATS systems)
3. **Rank Score:** Find most relevant candidates for specific job requirements

---

## ⚠️ Limitations

- **Experience calculation** may not be 100% accurate (depends on date format in resume)
- **Skills detection** only finds predefined common skills
- **Education detection** may miss non-standard formats
- **Certifications** only detects common ones

---

## 🔄 Future Improvements

Potential enhancements:
- Machine learning-based scoring
- Customizable scoring weights
- Industry-specific skill detection
- Better date parsing for experience
- NLP-based education extraction


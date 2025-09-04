import os
import json
import re
import google.generativeai as genai
from typing import Dict, Any, List
from datetime import datetime
from parsing.parsing_utils import extract_email

def initialize_gemini():
    try:
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
        return genai.GenerativeModel('gemini-2.0-flash') #pro , #flash, #gemini-1.5-flash-latest
    except Exception as e:
        raise Exception(f"Gemini initialization failed: {str(e)}")

def analyze_resume_comprehensive(resume_text: str, jd_data: Dict[str, Any], model) -> Dict[str, Any]:
    today = datetime.now().strftime("%m/%Y")

    prompt = f"""
    Perform a comprehensive analysis of this resume against the job description with the following components:
    CANDIDATE IDENTIFICATION:
        - Extract candidate_name (full name from resume header section)
        - If no name can be identified, return "Not specified"
    1. SKILL MATCH ANALYSIS:
        - Calculate match_score (0-100) **based ONLY on primary skill matches**
        - List matching_skills (only primary skills that are found)
        - List missing_primary_skills (primary skills not found)
        - List matching_secondary_skills (secondary skills found — NOT used for match_score)
        - List missing_secondary_skills (secondary skills not found)

        Note: Do NOT include secondary skills in match_score calculation. They are only for profile feedback.
    
    2. EXPERIENCE ANALYSIS:
       - Extract all work positions with:
         * company
         * title
         * duration (normalized to MM/YYYY-MM/YYYY format)
         * duration_length (calculated precisely in X years Y months format)
         * domain
         * internship flag
         * employment_type (full-time, contract, freelance, internship)
       - For positions missing dates: mark with "duration_missing": true
       - Calculate total_experience by summing duration_length of all non-internship positions
       - If no companies found, mark as fresher
       - Determine experience_match (boolean if meets JD requirements)
    
    3. PROFILE FEEDBACK:
       - freelancer_status: true if any position is freelance/contract (mention in summary)
       - has_linkedin: true if LinkedIn URL found (show URL if available)
       - has_email: true if email found (show email if available)
    
    4. IMPROVEMENT SUGGESTIONS:
       - List specific suggestions for improving resume
    
    5. SUMMARY:
       - Provide overall assessment including:
         * Experience status
         * If any matching secondary skills are found, mention them as "Additional Advantage: [skill1, skill2,...]"
    
    Rules for Experience Analysis:
    - Normalize all dates to MM/YYYY format
    - Handle "Present" as {today}
    - Exclude internships from total experience calculation
    - For total_experience, sum all duration_length values from non-internship positions
    - If multiple "Present" roles, mark as "Present (Current)"
    - If any position is missing dates, include in analysis but mark appropriately
    - If no companies found, clearly indicate this is a fresher profile
    
    Required Experience from JD: {jd_data.get('required_experience', 'Not specified')}
    Min Experience: {jd_data.get('min_experience', 0)} years
    Max Experience: {jd_data.get('max_experience', 0)} years
    
    Resume:
    {resume_text}
    
    Job Description Data:
    {json.dumps(jd_data, indent=2)}
    
    Return STRICT JSON format with this structure:
    {{  
        "candidate_info": {{
            "candidate_name": "John Doe"
        }},
        "skill_analysis": {{
            "match_score": 75,
            "matching_skills": ["Python", "ML"],
            "missing_primary_skills": ["AWS"],
            "missing_secondary_skills": ["Docker"]
        }},
        "experience_analysis": {{
            "positions": [
                {{
                    "company": "ABC Corp",
                    "title": "Software Engineer",
                    "duration": "01/2020 - 06/2022",
                    "duration_length": "2 years 5 months",
                    "domain": "IT",
                    "is_internship": false,
                    "employment_type": "full-time",
                    "duration_missing": false
                }}
            ],
            "total_experience": "2 years 5 months",
            "experience_match": true,
            "is_fresher": false,
            "positions_with_missing_dates": 1,
            "experience_status": "Partial dates available (1 position missing dates)"
        }},
        "profile_feedback": {{
            "freelancer_status": false,
            "has_linkedin": true,
            "linkedin_url": "https://linkedin.com/in/example",
            "has_email": true,
            "candidate_email": "example@email.com"
        }},
        "suggestions": ["Add AWS certification", "Add missing employment dates"],
        "summary": "Strong technical skills but lacks cloud experience. Partial work history available."
    }}
    
    Return ONLY valid JSON with no additional text or formatting.
    """

    try:
        response = model.generate_content(prompt)
        result = parse_gemini_response(response.text)

        # Ensure candidate_info exists in the result
        if "candidate_info" not in result:
            result["candidate_info"] = {"candidate_name": "Not specified"}

        # Initialize profile feedback if not present
        if "profile_feedback" not in result:
            result["profile_feedback"] = {
                "freelancer_status": False,
                "has_linkedin": False,
                "linkedin_url": "",
                "has_email": False,
                "candidate_email": ""
            }

        # Extract LinkedIn and email from resume text if not found by Gemini
        if not result["profile_feedback"]["has_linkedin"]:
            linkedin_url = extract_linkedin_url(resume_text)
            if linkedin_url:
                result["profile_feedback"]["has_linkedin"] = True
                result["profile_feedback"]["linkedin_url"] = linkedin_url

        if not result["profile_feedback"]["has_email"]:
            email = extract_email(resume_text)
            if email:
                result["profile_feedback"]["has_email"] = True
                result["profile_feedback"]["candidate_email"] = email

        # Determine freelancer status from positions if not set
        # if not result["profile_feedback"].get("freelancer_status", False):
        #     if "experience_analysis" in result:
        #         positions = result["experience_analysis"].get("positions", [])
        #         for position in positions:
        #             if position.get("employment_type", "").lower() in ["freelance", "contract"]:
        #                 result["profile_feedback"]["freelancer_status"] = True
        #                 break
        if not result["profile_feedback"].get("freelancer_status", False):
            if "experience_analysis" in result:
                positions = result["experience_analysis"].get("positions", [])
                for position in positions:
                    employment_type = position.get("employment_type")
                    if employment_type and isinstance(employment_type, str):
                        if employment_type.lower() in ["freelance", "contract"]:
                            result["profile_feedback"]["freelancer_status"] = True
                            break


        # Enhance summary with profile feedback
        summary_additions = []
        profile_feedback = result["profile_feedback"]
        
        if profile_feedback.get("freelancer_status", False):
            summary_additions.append("Has freelance/contract experience")
            
        if profile_feedback.get("has_linkedin", False):
            summary_additions.append("LinkedIn profile available")
        else:
            summary_additions.append("LinkedIn missing")
            
        if profile_feedback.get("has_email", False):
            summary_additions.append("Contact email available")
        else:
            summary_additions.append("Contact email missing")
            
        if summary_additions:
            if "summary" in result:
                result["summary"] += " " + ". ".join(summary_additions) + "."
            else:
                result["summary"] = ". ".join(summary_additions) + "."

        # Rest of the existing processing...
        if "experience_analysis" in result:
            exp_analysis = result["experience_analysis"]
            positions = exp_analysis.get("positions", [])
            missing_dates_count = sum(1 for p in positions if p.get("duration_missing", False))
            exp_analysis["positions_with_missing_dates"] = missing_dates_count

            if not positions:
                exp_analysis["is_fresher"] = True
                exp_analysis["experience_status"] = "Fresher (no work experience found)"
                exp_analysis["total_experience"] = "0 years"
            else:
                exp_analysis["is_fresher"] = False
                if missing_dates_count == 0:
                    exp_analysis["experience_status"] = "Complete dates available"
                elif missing_dates_count == len(positions):
                    exp_analysis["experience_status"] = "No dates available for any position"
                else:
                    exp_analysis["experience_status"] = f"Partial dates available ({missing_dates_count} positions missing dates)"

                total_months = 0
                valid_positions = 0
                for position in positions:
                    if not position.get("is_internship", False) and not position.get("duration_missing", False):
                        duration = position.get("duration_length", "")
                        if duration and duration != "N/A":
                            try:
                                years_match = re.search(r"(\d+)\s*year", duration)
                                months_match = re.search(r"(\d+)\s*month", duration)
                                years = int(years_match.group(1)) if years_match else 0
                                months = int(months_match.group(1)) if months_match else 0
                                total_months += years * 12 + months
                                valid_positions += 1
                            except:
                                continue

                if valid_positions > 0:
                    years = total_months // 12
                    months = total_months % 12
                    total_exp_str = f"{years} years {months} months" if months else f"{years} years"
                    exp_analysis["total_experience"] = total_exp_str
                else:
                    exp_analysis["total_experience"] = "Unable to calculate (missing dates)"

                # Experience Match Logic
                required_exp_str = jd_data.get("required_experience", "").strip()
                total_years = total_months / 12
                experience_match = False

                if "+" in required_exp_str:
                    try:
                        min_exp = int(required_exp_str.replace("+", "").strip())
                        experience_match = total_years >= min_exp
                    except:
                        experience_match = False
                elif "-" in required_exp_str:
                    try:
                        parts = required_exp_str.split("-")
                        min_exp = int(parts[0].strip())
                        max_exp = int(parts[1].strip())
                        experience_match = min_exp <= total_years <= max_exp
                    except:
                        experience_match = False
                elif required_exp_str.isdigit():
                    experience_match = total_years >= int(required_exp_str)
                else:
                    experience_match = False

                exp_analysis["experience_match"] = experience_match
                

            if missing_dates_count > 0:
                if "suggestions" not in result:
                    result["suggestions"] = []
                result["suggestions"].append(f"Add missing employment dates for {missing_dates_count} position(s)")

            if exp_analysis.get("is_fresher", False):
                if "summary" in result:
                    result["summary"] = "Fresher profile. " + result["summary"]
                else:
                    result["summary"] = "Fresher profile with no prior work experience"

        result["analysis_type"] = "comprehensive"
        return result

    except Exception as e:
        raise Exception(f"Comprehensive analysis failed: {str(e)}")

def extract_linkedin_url(text: str) -> str:
    """Extract LinkedIn URL from text using regex"""
    linkedin_pattern = r"(https?:\/\/(www\.)?linkedin\.com\/in\/[a-zA-Z0-9\-_]+\/?)"
    match = re.search(linkedin_pattern, text)
    return match.group(0) if match else ""


def parse_gemini_response(response_text: str) -> Dict[str, Any]:
    try:
        clean_text = response_text.strip()
        if clean_text.startswith("```json"):
            clean_text = clean_text[7:-3].strip()
        elif clean_text.startswith("```"):
            clean_text = clean_text[3:-3].strip()
        return json.loads(clean_text)
    except json.JSONDecodeError:
        return {
            "skill_analysis": {
                "match_score": extract_value(response_text, "match_score", int),
                "matching_skills": extract_list(response_text, "matching_skills"),
                "missing_primary_skills": extract_list(response_text, "missing_primary_skills"),
                "missing_secondary_skills": extract_list(response_text, "missing_secondary_skills")
            },
            "experience_analysis": {
                "positions": extract_experience_positions(response_text),
                "total_experience": extract_value(response_text, "total_experience", str),
                "experience_match": extract_value(response_text, "experience_match", bool)
            },
            "suggestions": extract_list(response_text, "suggestions"),
            "summary": extract_value(response_text, "summary", str)
        }

def extract_experience_positions(text: str) -> List[Dict]:
    positions = []
    position_blocks = re.findall(r'\{(.*?)\}', text, re.DOTALL)
    
    for block in position_blocks:
        positions.append({
            "company": extract_value(block, "company", str),
            "title": extract_value(block, "title", str),
            "duration": extract_value(block, "duration", str),
            "domain": extract_value(block, "domain", str),
            "is_internship": extract_value(block, "is_internship", bool)
        })
    return positions

def extract_value(text: str, key: str, type_func) -> Any:
    match = re.search(f'"{key}":\s*([^,\n}}]+)', text)
    if match:
        try:
            return type_func(match.group(1).strip(' "\''))
        except:
            return type_func()
    return type_func()

def extract_list(text: str, key: str) -> List[str]:
    match = re.search(f'"{key}":\s*\[([^\]]+)\]', text)
    if match:
        return [item.strip(' "\'') for item in match.group(1).split(",") if item.strip()]
    return []
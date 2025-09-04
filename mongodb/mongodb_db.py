import os
from pymongo import MongoClient
from datetime import datetime
import uuid
from typing import Dict, List, Optional, Set
from utils.common_utils import to_init_caps
from parsing.parsing_utils import extract_email
from dotenv import load_dotenv
from pathlib import Path
from bson import Binary

def initialize_mongodb():
    # Load .env from the project root
    env_path = Path(__file__).parent.parent / '.env'
    load_dotenv(dotenv_path=env_path)
    
    MONGO_URI = os.getenv("MONGO_URI")
    db_name = os.getenv("MONGO_DB")
    
    if not MONGO_URI:
        raise ValueError("MONGO_URI environment variable is not set")
    
    try:
        client = MongoClient(MONGO_URI)
        return client[db_name]
    except Exception as e:
        raise Exception(f"Failed to initialize MongoDB client: {str(e)}")

db = initialize_mongodb()

def store_results_in_mongodb(analysis_data: Dict, jd_data: Dict, filename: str, 
                          resume_text: str, file_content: bytes, client_name: str, 
                          job_description: str, created_by: str, company_id: str) -> Optional[str]:
    try:
        # Get or create client
        client_doc = db.clients.find_one({
            "client_name": to_init_caps(client_name),
            "company_id": company_id
        })
        if client_doc:
            client_id = client_doc["_id"]
        else:
            # Create new client
            new_client = {
                "client_name": to_init_caps(client_name),
                "company_id": company_id,
                "created_by": created_by,
                "created_at": datetime.now()
            }
            client_id = db.clients.insert_one(new_client).inserted_id
            client_doc = new_client
        
        # Get or create job description
        jd_doc = db.job_descriptions.find_one({
            "client_id": client_id,
            "jd_title": to_init_caps(job_description),
            "company_id": company_id
        })
        
        if jd_doc:
            jd_id = jd_doc["_id"]
        else:
            # Create new job description
            new_jd = {
                "client_id": client_id,
                "jd_title": to_init_caps(job_description),
                "required_experience": jd_data.get("required_experience", ""),
                "primary_skills": jd_data.get("primary_skills", []),
                "secondary_skills": jd_data.get("secondary_skills", []),
                "company_id": company_id,
                "created_by": created_by,
                "created_at": datetime.now()
            }
            jd_id = db.job_descriptions.insert_one(new_jd).inserted_id
            jd_doc = new_jd
        
        # Store analysis
        analysis_id = str(uuid.uuid4())
        candidate_email = extract_email(resume_text)
        candidate_name = analysis_data.get("candidate_info", {}).get("candidate_name", "Not specified")
        
        # Get profile feedback data
        profile_feedback = analysis_data.get("profile_feedback", {})
        
        analysis_record = {
            "analysis_id": analysis_id,
            "timestamp": datetime.now(),
            "candidate_name": candidate_name,
            "filename": filename,
            "file_content": Binary(file_content),  # Store file content as BSON Binary
            "client_id": client_id,
            "client_name": client_doc["client_name"],
            "jd_id": jd_id,
            "jd_title": jd_doc["jd_title"],
            "required_experience": jd_doc.get("required_experience", ""),
            "primary_skills": jd_doc.get("primary_skills", []),
            "secondary_skills": jd_doc.get("secondary_skills", []),
            "candidate_email": candidate_email,
            "freelancer_status": profile_feedback.get("freelancer_status", False),
            "has_linkedin": profile_feedback.get("has_linkedin", False),
            "linkedin_url": profile_feedback.get("linkedin_url", ""),
            "has_email": profile_feedback.get("has_email", False),
            "match_score": analysis_data.get("skill_analysis", {}).get("match_score", 0),
            "experience_match": analysis_data.get("experience_analysis", {}).get("experience_match", False),
            "total_experience": analysis_data.get("experience_analysis", {}).get("total_experience", "N/A"),
            "matching_skills": analysis_data.get("skill_analysis", {}).get("matching_skills", []),
            "missing_primary_skills": analysis_data.get("skill_analysis", {}).get("missing_primary_skills", []),
            "missing_secondary_skills": analysis_data.get("skill_analysis", {}).get("missing_secondary_skills", []),
            "company_id": company_id,
            "created_by": created_by,
        }
        
        db.analysis_history.insert_one(analysis_record)
        
        return analysis_id

    except Exception as e:
        raise Exception(f"Failed to store results in MongoDB: {str(e)}")

# def fetch_analysis_history(current_user: dict) -> List[Dict]:
#     try:
#         query = {"company_id": current_user["company_id"]}
        
#         # If user is not admin, only show their analyses
#         if current_user["role"] != "company_admin":
#             query["created_by"] = current_user["id"]
            
#         # Exclude file_content from the query to reduce payload size
#         history = list(db.analysis_history.find(
#             query, 
#             {"file_content": 0}  # Exclude file content from results
#         ).sort("timestamp", -1))
        
#         # Convert ObjectId to string for JSON serialization
#         for item in history:
#             item["_id"] = str(item["_id"])
#             if "client_id" in item:
#                 item["client_id"] = str(item["client_id"])
#             if "jd_id" in item:
#                 item["jd_id"] = str(item["jd_id"])
#         return history
    
#     except Exception as e:
#         raise Exception(f"Failed to fetch history: {str(e)}")

def fetch_analysis_history(current_user: dict) -> List[Dict]:
    try:
        # Build query based on user role - only for analysis history
        if current_user["role"] == "company_admin":
            # Company admin can see all analyses for their company
            query = {"company_id": current_user["company_id"]}
        elif current_user["role"] == "user":
            # Regular user can only see their own analyses within their company
            query = {
                "company_id": current_user["company_id"],
                "created_by": current_user["id"]
            }
        else:
            # For other roles, return empty
            query = {"company_id": "invalid_id"}  # Ensure no results
            # Alternatively, you could raise an error:
            # raise Exception("Unauthorized role for history access")
            
        # Exclude file_content from the query to reduce payload size
        history = list(db.analysis_history.find(
            query, 
            {"file_content": 0}  # Exclude file content from results
        ).sort("timestamp", -1))
        
        # Convert ObjectId to string for JSON serialization
        for item in history:
            item["_id"] = str(item["_id"])
            if "client_id" in item:
                item["client_id"] = str(item["client_id"])
            if "jd_id" in item:
                item["jd_id"] = str(item["jd_id"])
        return history
    
    except Exception as e:
        raise Exception(f"Failed to fetch history: {str(e)}")

# Update the fetch_client_names function
def fetch_client_names(company_id: str) -> Set[str]:
    try:
        client_names = db.clients.distinct("client_name", {"company_id": company_id})
        return set(sorted(client_names))
    except Exception as e:
        raise Exception(f"Failed to fetch client names: {str(e)}")

def fetch_client_details(client_name: str, company_id: str) -> Optional[Dict]:
    try:
        client_doc = db.clients.find_one({
            "client_name": to_init_caps(client_name),
            "company_id": company_id
        })
        
        if not client_doc:
            return None
            
        client_id = client_doc["_id"]
        
        # Get the most recent job description for this client
        jd_doc = db.job_descriptions.find_one(
            {"client_id": client_id, "company_id": company_id},
            sort=[("created_at", -1)]
        )
        
        if not jd_doc:
            return None
            
        return {
            "job_description": jd_doc.get("jd_title", ""),
            "required_experience": jd_doc.get("required_experience", ""),
            "primary_skills": jd_doc.get("primary_skills", []),
            "secondary_skills": jd_doc.get("secondary_skills", [])
        }
    except Exception as e:
        raise Exception(f"Failed to fetch client details: {str(e)}")

def fetch_jd_names_for_client(client_name: str, company_id: str) -> Optional[List[str]]:
    try:
        client_doc = db.clients.find_one({
            "client_name": to_init_caps(client_name),
            "company_id": company_id
        })
        
        if not client_doc:
            return None
            
        client_id = client_doc["_id"]
        
        jd_names = db.job_descriptions.distinct(
            "jd_title",
            {"client_id": client_id, "company_id": company_id}
        )
        
        return jd_names if jd_names else None
    except Exception as e:
        raise Exception(f"Failed to fetch JD names for client: {str(e)}")

def fetch_client_details_by_jd(client_name: str, jd_name: str, company_id: str) -> Optional[Dict]:
    try:
        client_doc = db.clients.find_one({
            "client_name": to_init_caps(client_name),
            "company_id": company_id
        })
        
        if not client_doc:
            return None
            
        client_id = client_doc["_id"]
        
        jd_doc = db.job_descriptions.find_one({
            "client_id": client_id,
            "jd_title": to_init_caps(jd_name),
            "company_id": company_id
        })
        
        if not jd_doc:
            return None
            
        return {
            "job_description": jd_doc.get("jd_title", ""),
            "required_experience": jd_doc.get("required_experience", ""),
            "primary_skills": jd_doc.get("primary_skills", []),
            "secondary_skills": jd_doc.get("secondary_skills", [])
        }
    except Exception as e:
        raise Exception(f"Failed to fetch client details by JD: {str(e)}")
    
def update_job_description(client_name: str, jd_name: str, required_experience: str, 
                         primary_skills: list, secondary_skills: list, company_id: str) -> bool:
    """
    Update the job description details for a given client and JD name in MongoDB
    """
    try:
        client_doc = db.clients.find_one({
            "client_name": to_init_caps(client_name),
            "company_id": company_id
        })
        if not client_doc:
            return False
            
        client_id = client_doc["_id"]
        
        jd_doc = db.job_descriptions.find_one({
            "client_id": client_id,
            "jd_title": to_init_caps(jd_name),
            "company_id": company_id
        })
        if not jd_doc:
            return False
            
        result = db.job_descriptions.update_one(
            {"_id": jd_doc["_id"]},
            {"$set": {
                "required_experience": required_experience,
                "primary_skills": primary_skills,
                "secondary_skills": secondary_skills
            }}
        )
        
        return result.modified_count > 0
    except Exception as e:
        print(f"Failed to update job description: {e}")
        return False
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import bcrypt
import os
from dotenv import load_dotenv
from typing import Optional
import uuid
from datetime import datetime, timedelta
import smtplib, ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pymongo import MongoClient
from pymongo.collection import ReturnDocument
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from typing import List, Optional, Any, Dict
import json
import os
import tempfile
from fastapi.responses import JSONResponse, StreamingResponse
from io import BytesIO

from dotenv import load_dotenv

from llama.llama_utils import initialize_llama_parser
from parsing.parsing_utils import parse_resume
from gemini.gemini_utils import analyze_resume_comprehensive, initialize_gemini
from mongodb.mongodb_db import (
    initialize_mongodb,
    fetch_analysis_history,
    fetch_client_names,
    fetch_client_details_by_jd,
    fetch_jd_names_for_client,
    store_results_in_mongodb,
    update_job_description,
)

load_dotenv()

# --------------------
# Environment / Clients
# --------------------
MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB = os.getenv("MONGO_DB")
client = MongoClient(MONGO_URI)
db = client[MONGO_DB]
col_super_admins = db["super_admins"]
col_companies = db["companies"]
col_company_users = db["company_users"]
col_password_resets = db["password_resets"]

SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT")) if os.getenv("SMTP_PORT") else None
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
SMTP_FROM = os.getenv("SMTP_FROM") or SMTP_USER
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://127.0.0.1:8000")
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

app = FastAPI()

# Allow frontend to talk to backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Change to your domain later for security
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"]
)

# --------------------
# Models
# --------------------
class LoginRequest(BaseModel):
    email: str
    password: str

class CompanyCreate(BaseModel):
    name: str
    description: str
    address: str
    admin_email: str
    admin_password: str

class CompanyUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    address: Optional[str] = None

class UserCreate(BaseModel):
    email: str
    password: str
    name: str
    role: Optional[str] = None  # ignored; always 'user'
    company_id: str

class UserUpdate(BaseModel):
    email: Optional[str] = None
    password: Optional[str] = None
    name: Optional[str] = None
    role: Optional[str] = None
    company_id: Optional[str] = None

class CompanyResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    address: Optional[str]
    created_at: str

class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    role: str
    company_id: str
    created_at: str

class PasswordResetRequest(BaseModel):
    email: str
    new_password: str

class PasswordResetConfirm(BaseModel):
    token: str

class JDData(BaseModel):
    client_name: str = Field(..., description="Client name")
    jd_title: str = Field(..., description="Job description title")
    required_experience: Optional[str] = Field(None, description="e.g., '3-5', '4+'")
    min_experience: Optional[int] = None
    max_experience: Optional[int] = None
    primary_skills: List[str] = Field(default_factory=list)
    secondary_skills: List[str] = Field(default_factory=list)


class UpdateJD(BaseModel):
    required_experience: str
    primary_skills: List[str]
    secondary_skills: List[str] = []


def _ensure_env_loaded():
    # Load .env from current working directory (project root)
    load_dotenv()
# --------------------
# Auth guard (header role)
# --------------------

def require_super_admin(x_user_role: Optional[str] = Header(default=None)) -> str:
    if x_user_role != "super_admin":
        raise HTTPException(status_code=403, detail="Super admin privilege required")
    return x_user_role

# --------------------
# SMTP helper
# --------------------

def send_reset_email(to_email: str, token: str):
    if not (SMTP_HOST and SMTP_PORT and SMTP_FROM):
        raise RuntimeError("SMTP not configured. Set SMTP_HOST, SMTP_PORT, SMTP_USER/SMTP_FROM, SMTP_PASS")

    confirm_link = f"{APP_BASE_URL}/password-reset/confirm/{token}"
    subject = "Password Reset Request"
    html = f"""
    <div style='font-family:Arial,sans-serif;font-size:14px;color:#333;'>
      <p>You requested to reset your password.</p>
      <p>This link expires in <strong>1 minute</strong>. Click the button below to confirm your password change:</p>
      <p style='margin:16px 0;'>
        <a href="{confirm_link}" style='background:#667eea;color:#fff;padding:10px 16px;border-radius:6px;text-decoration:none;'>Confirm Password Reset</a>
      </p>
      <p>If the button doesn't work, copy and paste this URL into your browser:</p>
      <p><a href="{confirm_link}">{confirm_link}</a></p>
      <p>If you didn't request this, please ignore this email.</p>
    </div>
    """

    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = SMTP_FROM
    message["To"] = to_email
    message.attach(MIMEText(html, "html"))

    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    context.minimum_version = ssl.TLSVersion.TLSv1_2

    try:
        if SMTP_PORT == 587:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
                server.ehlo()
                if server.has_extn('STARTTLS'):
                    server.starttls(context=context)
                    server.ehlo()
                if SMTP_USER and SMTP_PASS:
                    server.login(SMTP_USER, SMTP_PASS)
                server.sendmail(SMTP_FROM, to_email, message.as_string())
        elif SMTP_PORT == 465:
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context, timeout=10) as server:
                if SMTP_USER and SMTP_PASS:
                    server.login(SMTP_USER, SMTP_PASS)
                server.sendmail(SMTP_FROM, to_email, message.as_string())
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
                server.ehlo()
                if server.has_extn('STARTTLS'):
                    server.starttls(context=context)
                    server.ehlo()
                if SMTP_USER and SMTP_PASS:
                    server.login(SMTP_USER, SMTP_PASS)
                server.sendmail(SMTP_FROM, to_email, message.as_string())
    except Exception as e:
        raise RuntimeError(f"Failed to send email: {str(e)}")

# --------------------
# Auth
# --------------------
@app.post("/login")

def login(data: LoginRequest):
    # Super admin
    sa = col_super_admins.find_one({"email": data.email})
    if sa and bcrypt.checkpw(data.password.encode("utf-8"), sa["password"].encode("utf-8")):
        return {
            "message": "Login successful",
            "role": "super_admin",
            "name": sa.get("name"),
            "user_id": sa.get("id", str(uuid.uuid4())),
            "email": sa.get("email"),
            "token": str(uuid.uuid4())
        }

    # Company users
    cu = col_company_users.find_one({"email": data.email})
    if cu and bcrypt.checkpw(data.password.encode("utf-8"), cu["password"].encode("utf-8")):
        return {
            "message": "Login successful",
            "role": cu.get("role"),
            "name": cu.get("name"),
            "user_id": cu.get("id", str(uuid.uuid4())),
            "email": cu.get("email"),
            "company_id": cu.get("company_id"),
            "created_at": cu.get("created_at"),
            "token": str(uuid.uuid4())
        }

    raise HTTPException(status_code=401, detail="Invalid email or password")

# --------------------
# Companies
# --------------------
@app.post("/companies", response_model=CompanyResponse)

def create_company(company: CompanyCreate, _: str = Depends(require_super_admin)):
    # Duplicate checks
    if col_companies.find_one({"name": company.name}):
        raise HTTPException(status_code=400, detail="Company name already exists")
    if col_company_users.find_one({"email": company.admin_email}):
        raise HTTPException(status_code=400, detail="Admin email already exists")

    now_iso = datetime.now().isoformat()
    company_id = str(uuid.uuid4())
    company_doc = {
        "_id": company_id,
        "id": company_id,
        "name": company.name,
        "description": company.description,
        "address": company.address,
        "created_at": now_iso
    }
    col_companies.insert_one(company_doc)

    # Initial company admin
    admin_id = str(uuid.uuid4())
    admin_doc = {
        "_id": admin_id,
        "id": admin_id,
        "email": company.admin_email,
        "password": bcrypt.hashpw(company.admin_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8"),
        "name": company.name,
        "role": "company_admin",
        "company_id": company_id,
        "created_at": now_iso
    }
    try:
        col_company_users.insert_one(admin_doc)
    except Exception as e:
        # Keep company, but surface in logs
        print("Failed to create company admin:", str(e))

    return CompanyResponse(**company_doc)

@app.get("/companies")

def get_companies():
    items = []
    for doc in col_companies.find({}, {"_id": 0}):
        items.append(doc)
    return items

@app.patch("/companies/{company_id}", response_model=CompanyResponse)

def update_company(company_id: str, company: CompanyUpdate, _: str = Depends(require_super_admin)):
    update_data = {k: v for k, v in company.dict(exclude_unset=True).items() if v is not None}
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")

    updated = col_companies.find_one_and_update(
        {"id": company_id},
        {"$set": update_data},
        return_document=ReturnDocument.AFTER,
        projection={"_id": 0}
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Company not found")
    return CompanyResponse(**updated)

@app.delete("/companies/{company_id}")

def delete_company(company_id: str, _: str = Depends(require_super_admin)):
    # Prevent delete if users still exist in company
    if col_company_users.count_documents({"company_id": company_id}) > 0:
        raise HTTPException(status_code=400, detail="First remove this company's users, then delete the company.")
    res = col_companies.delete_one({"id": company_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Company not found")
    return {"message": "Company deleted"}

# --------------------
# Users
# --------------------
@app.post("/users", response_model=UserResponse)

def create_user(user: UserCreate, _: str = Depends(require_super_admin)):
    try:
        now_iso = datetime.now().isoformat()
        user_id = str(uuid.uuid4())
        user_doc = {
            "_id": user_id,
            "id": user_id,
            "email": user.email,
            "password": bcrypt.hashpw(user.password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8"),
            "name": user.name,
            "role": "user",
            "company_id": user.company_id,
            "created_at": now_iso
        }
        col_company_users.insert_one(user_doc)
        return UserResponse(**{k: v for k, v in user_doc.items() if k != "_id"})
    except Exception as e:
        print("Error in create_user:", str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.patch("/users/{user_id}", response_model=UserResponse)

def update_user(user_id: str, user: UserUpdate, _: str = Depends(require_super_admin)):
    update_data = {k: v for k, v in user.dict(exclude_unset=True).items() if v is not None}
    if "password" in update_data:
        update_data["password"] = bcrypt.hashpw(update_data["password"].encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")

    updated = col_company_users.find_one_and_update(
        {"id": user_id},
        {"$set": update_data},
        return_document=ReturnDocument.AFTER
    )
    if not updated:
        raise HTTPException(status_code=404, detail="User not found")
    updated.pop("_id", None)
    return UserResponse(**updated)

@app.delete("/users/{user_id}")

def delete_user(user_id: str, _: str = Depends(require_super_admin)):
    res = col_company_users.delete_one({"id": user_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
    return {"message": "User deleted"}

@app.get("/users")

def get_users(company_id: Optional[str] = None):
    query = {}
    if company_id:
        query["company_id"] = company_id
    items = []
    for doc in col_company_users.find(query, {"_id": 0}):
        items.append(doc)
    return items

# --------------------
# Dashboard
# --------------------
@app.get("/dashboard")

def get_dashboard_data():
    companies_count = col_companies.count_documents({})
    users_count = col_company_users.count_documents({})
    return {
        "companies_count": companies_count,
        "users_count": users_count
    }

# --------------------
# Password reset
# --------------------

def _find_user_by_email(email: str):
    sa = col_super_admins.find_one({"email": email})
    if sa:
        return ("super_admins", sa)
    cu = col_company_users.find_one({"email": email})
    if cu:
        return ("company_users", cu)
    return (None, None)

@app.post("/password-reset/request")

def password_reset_request(data: PasswordResetRequest):
    if not data.email or not data.new_password:
        raise HTTPException(status_code=400, detail="Email and new password are required")
    if len(data.new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    table, user = _find_user_by_email(data.email)
    if not user:
        raise HTTPException(status_code=404, detail="Email not found")

    token = str(uuid.uuid4())
    expires_at = (datetime.utcnow() + timedelta(minutes=1)).isoformat() + "Z"
    hashed_new_password = bcrypt.hashpw(data.new_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    row_id = str(uuid.uuid4())
    reset_row = {
        "_id": row_id,
        "id": row_id,
        "email": data.email,
        "token": token,
        "new_password_hash": hashed_new_password,
        "user_table": table,
        "expires_at": expires_at,
        "created_at": datetime.utcnow().isoformat()
    }

    col_password_resets.insert_one(reset_row)

    try:
        send_reset_email(data.email, token)
    except Exception as e:
        print("Failed to send email:", str(e))
        msg = "Failed to send reset email"
        if DEBUG:
            msg += f": {str(e)}"
        raise HTTPException(status_code=500, detail=msg)

    return {"message": "Password reset email sent"}

@app.post("/password-reset/confirm/{token}", response_model=dict)

def password_reset_confirm(token: str):
    if not token:
        raise HTTPException(status_code=400, detail="Token is required")

    row = col_password_resets.find_one({"token": token})
    if not row:
        raise HTTPException(status_code=400, detail="Invalid or expired token")

    try:
        if datetime.utcnow() > datetime.fromisoformat(row["expires_at"].replace("Z", "")):
            col_password_resets.delete_one({"id": row["id"]})
            raise HTTPException(status_code=400, detail="Token expired")
    except Exception:
        col_password_resets.delete_one({"id": row.get("id")})
        raise HTTPException(status_code=400, detail="Invalid token")

    target = row.get("user_table")
    if target == "super_admins":
        upd = col_super_admins.update_one({"email": row["email"]}, {"$set": {"password": row["new_password_hash"]}})
    elif target == "company_users":
        upd = col_company_users.update_one({"email": row["email"]}, {"$set": {"password": row["new_password_hash"]}})
    else:
        col_password_resets.delete_one({"id": row.get("id")})
        raise HTTPException(status_code=400, detail="Invalid token context")

    if upd.modified_count == 0:
        raise HTTPException(status_code=500, detail="Failed to update password")

    col_password_resets.delete_one({"id": row.get("id")})
    return {"message": "Password reset successful"}

@app.get("/password-reset/confirm/{token}", response_class=HTMLResponse)

def password_reset_confirm_get(token: str):
    row = col_password_resets.find_one({"token": token})
    if not row:
        return HTMLResponse("<h3>Invalid or expired token</h3>", status_code=400)

    try:
        if datetime.utcnow() > datetime.fromisoformat(row["expires_at"].replace("Z", "")):
            col_password_resets.delete_one({"id": row["id"]})
            return HTMLResponse("<h3>Token expired</h3>", status_code=400)
    except Exception:
        col_password_resets.delete_one({"id": row.get("id")})
        return HTMLResponse("<h3>Invalid token</h3>", status_code=400)

    target = row.get("user_table")
    if target == "super_admins":
        upd = col_super_admins.update_one({"email": row["email"]}, {"$set": {"password": row["new_password_hash"]}})
    elif target == "company_users":
        upd = col_company_users.update_one({"email": row["email"]}, {"$set": {"password": row["new_password_hash"]}})
    else:
        col_password_resets.delete_one({"id": row.get("id")})
        return HTMLResponse("<h3>Invalid token</h3>", status_code=400)

    if upd.modified_count == 0:
        return HTMLResponse("<h3>Failed to update password</h3>", status_code=500)

    col_password_resets.delete_one({"id": row.get("id")})
    return HTMLResponse("<h3>Password reset successful. You may close this window and log in.</h3>")


# --------------------
# Resume parser
# --------------------
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.on_event("startup")
def on_startup():
    _ensure_env_loaded()
    # Initialize Supabase client (module import also initializes it)
    try:
        #initialize_supabase()
        initialize_mongodb()
    except Exception:
        # Defer errors to first DB call
        pass
    # Initialize Gemini model once
    try:
        app.state.gemini_model = initialize_gemini()
    except Exception as e:
        app.state.gemini_model = None
        print(f"Gemini not initialized: {e}")


@app.get("/health")
def health() -> Dict[str, Any]:
    return {"ok": True, "gemini": bool(app.state.__dict__.get("gemini_model"))}

# Add this dependency to extract user info from the token
def get_current_user(request: Request, 
                   x_user_role: Optional[str] = Header(default=None), 
                   x_user_id: Optional[str] = Header(default=None),
                   x_company_id: Optional[str] = Header(default=None)):
    
    # Debug logging to identify header issues
    print(f"Auth headers - Role: {x_user_role}, User ID: {x_user_id}, Company ID: {x_company_id}")
    
    if not x_user_role or not x_user_id:
        # Check for alternative header names that might be sent from frontend
        alternative_user_id = request.headers.get('X-User-ID') or request.headers.get('X-UserId') or request.headers.get('User-Id')
        alternative_role = request.headers.get('X-User-Role') or request.headers.get('User-Role')
        
        if alternative_user_id and alternative_role:
            x_user_id = alternative_user_id
            x_user_role = alternative_role
            x_company_id = x_company_id or request.headers.get('X-Company-Id') or request.headers.get('Company-Id')
        else:
            raise HTTPException(status_code=401, detail="Not authenticated")
    
    return {
        "role": x_user_role,
        "id": x_user_id,
        "company_id": x_company_id
    }

@app.post("/analyze")
async def analyze_resume_endpoint(
    resume: UploadFile = File(..., description="Resume file (.pdf or .docx)"),
    jd_data: str = Form(..., description="JSON string for JDData"),
    current_user: dict = Depends(get_current_user)
) -> JSONResponse:
    
    try:
        jd: JDData = JDData(**json.loads(jd_data))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid jd_data JSON: {e}")

    # Read file content
    content = await resume.read()

    # Save uploaded file to a temp path for parsing
    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(resume.filename)[1]) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        # Parse resume using LlamaParse (json first, fallback to text)
        resume_text = ""
        try:
            parser_json = initialize_llama_parser("json")
            resume_text = parse_resume(tmp_path, parser_json)
        except Exception:
            parser_text = initialize_llama_parser("text")
            resume_text = parse_resume(tmp_path, parser_text)

        if not resume_text:
            raise HTTPException(status_code=422, detail="Failed to parse resume text")

        # Analyze with Gemini
        model = app.state.__dict__.get("gemini_model")
        if model is None:
            model = initialize_gemini()
            app.state.gemini_model = model

        analysis = analyze_resume_comprehensive(resume_text, jd.dict(), model)

        # Validate current_user data before storing
        if not current_user.get("id"):
            raise HTTPException(status_code=400, detail="User ID not found in authentication")
        
        if not current_user.get("company_id"):
            raise HTTPException(status_code=400, detail="Company ID not found in authentication")

        # Store in MongoDB with file
        store_key = store_results_in_mongodb(
            analysis,
            jd.dict(),
            resume.filename,
            resume_text,
            content,
            jd.client_name,
            jd.jd_title,
            current_user["id"],  # created_by
            current_user["company_id"]  # company_id
        )

        return JSONResponse(
            status_code=200,
            content={
                "analysis_id": store_key,
                "analysis": analysis,
            },
        )
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass

# @app.get("/history")
# def list_history() -> List[Dict[str, Any]]:
#     return fetch_analysis_history()


# @app.get("/clients")
# def list_clients() -> List[str]:
#     return fetch_client_names()
@app.get("/history")
def list_history(current_user: dict = Depends(get_current_user)) -> List[Dict[str, Any]]:
    return fetch_analysis_history(current_user)


@app.get("/download/{analysis_id}")
async def download_resume(analysis_id: str, current_user: dict = Depends(get_current_user)):
    try:
        # Get analysis record
        analysis = db.analysis_history.find_one({
            "analysis_id": analysis_id,
            "company_id": current_user["company_id"]
        })
        
        if not analysis:
            raise HTTPException(status_code=404, detail="Analysis not found")
            
        # If user is not admin, check if they created this analysis
        if current_user["role"] != "company_admin" and analysis["created_by"] != current_user["id"]:
            raise HTTPException(status_code=403, detail="Not authorized to access this resource")
        
        # Get file content from BSON Binary
        file_content = analysis["file_content"]
        
        # Return file as download
        return StreamingResponse(
            BytesIO(file_content),
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f"attachment; filename={analysis['filename']}"
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to download file: {str(e)}")

# Update the clients endpoint
@app.get("/clients")
def list_clients(current_user: dict = Depends(get_current_user)) -> List[str]:
    return fetch_client_names(current_user["company_id"])

# @app.get("/clients/{client_name}/jds")
# def list_jd_names(client_name: str) -> List[str]:
#     jd_names = fetch_jd_names_for_client(client_name)
#     return jd_names or []


# @app.get("/clients/{client_name}/jds/{jd_title}")
# def get_jd_details(client_name: str, jd_title: str) -> Dict[str, Any]:
#     jd = fetch_client_details_by_jd(client_name, jd_title)
#     if not jd:
#         raise HTTPException(status_code=404, detail="JD not found")
#     return jd


# @app.put("/clients/{client_name}/jds/{jd_title}")
# def put_update_jd(client_name: str, jd_title: str, body: UpdateJD) -> Dict[str, Any]:
#     success = update_job_description(
#         client_name,
#         jd_title,
#         body.required_experience,
#         body.primary_skills,
#         body.secondary_skills,
#     )
#     if not success:
#         raise HTTPException(status_code=400, detail="Failed to update job description")
#     return {"ok": True}
@app.get("/clients/{client_name}/jds")
def list_jd_names(client_name: str, current_user: dict = Depends(get_current_user)) -> List[str]:
    jd_names = fetch_jd_names_for_client(client_name, current_user["company_id"])
    return jd_names or []

@app.get("/clients/{client_name}/jds/{jd_title}")
def get_jd_details(client_name: str, jd_title: str, current_user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    jd = fetch_client_details_by_jd(client_name, jd_title, current_user["company_id"])
    if not jd:
        raise HTTPException(status_code=404, detail="JD not found")
    return jd

@app.put("/clients/{client_name}/jds/{jd_title}")
def put_update_jd(client_name: str, jd_title: str, body: UpdateJD, current_user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    success = update_job_description(
        client_name,
        jd_title,
        body.required_experience,
        body.primary_skills,
        body.secondary_skills,
        current_user["company_id"]
    )
    if not success:
        raise HTTPException(status_code=400, detail="Failed to update job description")
    return {"ok": True}

@app.get("/")
def root() -> Dict[str, Any]:
    return {
        "name": "TalentHive Resume Analyzer API",
        "version": "1.0.0",
        "endpoints": [
            "GET /health",
            "POST /analyze",
            "GET /history",
            "GET /clients",
            "GET /clients/{client_name}/jds",
            "GET /clients/{client_name}/jds/{jd_title}",
            "PUT /clients/{client_name}/jds/{jd_title}",
        ],
    }


@app.get("/ui")
def render_ui(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# --------------------
# Main
# --------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
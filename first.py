# import uuid, bcrypt
# from pymongo import MongoClient

# # db = MongoClient("mongodb://103.146.234.83:27017")["appdb"]
# #mongodb://mongouser:Mongouser_xyz@139.59.79.77:27017/tech_pack_dna?authSource=admin
# db = MongoClient("mongodb://tladmin:S#n7L*gJA!9_yM36@103.146.234.83:27017/?authSource=admin")
# # Optional: unique index
# db.super_admins.create_index("email", unique=True)

# password_hash = bcrypt.hashpw(b"123456", bcrypt.gensalt()).decode("utf-8")
# admin = {
#   "_id": str(uuid.uuid4()),
#   "id": str(uuid.uuid4()),
#   "name": "Super Admin",
#   "email": "super@gmail.com",
#   "password": password_hash,
#   "role": "super_admin",
#   "created_at": "2025-01-01T00:00:00Z"
# }
# db.super_admins.insert_one(admin)
# print("Seeded super admin")
import uuid, bcrypt
from pymongo import MongoClient

# Connect with proper DB
client = MongoClient("mongodb://tladmin:TlAdminDh@103.146.234.83:27017/?authSource=admin")

# Select database
db = client["tlrecruitdb"]

# Create unique index on email
db.super_admins.create_index("email", unique=True)

# Hash password
password_hash = bcrypt.hashpw(b"123456", bcrypt.gensalt()).decode("utf-8")

# Super admin document
admin = {
    "_id": str(uuid.uuid4()),   # internal unique ID
    "id": str(uuid.uuid4()),    # your own app ID
    "name": "Super Admin",
    "email": "super1@gmail.com",
    "password": password_hash,
    "role": "super_admin",
    "created_at": "2025-01-01T00:00:00Z"
}

# Insert document
result = db.super_admins.insert_one(admin)
print("✅ Seeded super admin with _id:", result.inserted_id)

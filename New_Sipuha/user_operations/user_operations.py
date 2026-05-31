from pydantic import BaseModel
from database.tables import UserRole

#For post requests
class UserLogin(BaseModel):
    username: str
    password: str

class UserRegister(BaseModel):
    username: str
    email: str
    password: str
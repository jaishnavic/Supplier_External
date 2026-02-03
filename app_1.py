from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
import os
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fusion_validator import validate_against_fusion
from fusion_client import create_supplier

app = FastAPI()
security = HTTPBasic()

def authenticate(credentials: HTTPBasicCredentials = Depends(security)):
    if credentials.username == os.getenv("AGENT_USERNAME") and credentials.password == os.getenv("AGENT_PASSWORD"):
        return credentials.username
    raise HTTPException(status_code=401)

class SupplierData(BaseModel):
    Supplier: str
    TaxOrganizationType: str
    SupplierType: str
    TaxpayerCountry: str
    TaxpayerId: str
    DUNSNumber: Optional[str] = None

@app.post("/validate-supplier")
def validate_tool(payload: SupplierData, username: str = Depends(authenticate)):
    """Validates data before the user confirms."""
    errors = validate_against_fusion(payload.dict())
    if errors:
        return {"success": False, "errors": errors}
    return {"success": True, "message": "Data is valid."}

@app.post("/create-supplier")
def create_tool(payload: SupplierData, username: str = Depends(authenticate)):
    """Final step: calls Fusion REST API."""
    status, response = create_supplier(payload.dict())
    if status == 201:
        return {"success": True, "SupplierId": response.get("SupplierId")}
    return {"success": False, "error": "Fusion API failure."}
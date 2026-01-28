from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
import os

from fastapi.security import HTTPBasic, HTTPBasicCredentials

from utils.session_manager import init_session, get_missing_fields
from fusion_validator import validate_against_fusion
from fusion_client import create_supplier
from config.fusion_settings import FIELD_QUESTIONS, REQUIRED_FIELDS, DEFAULT_VALUES

app = FastAPI()

# ---------------- AUTH ----------------
security = HTTPBasic()

def authenticate_user(credentials: HTTPBasicCredentials = Depends(security)):
    if (
        credentials.username == os.getenv("AGENT_USERNAME")
        and credentials.password == os.getenv("AGENT_PASSWORD")
    ):
        return credentials.username
    raise HTTPException(status_code=401, detail="Unauthorized")

# ---------------- REQUEST ----------------
class SupplierAgentRequest(BaseModel):
    message: str

# ---------------- SESSION ----------------
active_session = {"state": "INIT"}

@app.get("/")
def read_root():
    return {"status": "Supplier Agent is running."}

@app.post("/supplier-agent")
def supplier_agent(payload: SupplierAgentRequest, username: str = Depends(authenticate_user)):
    global active_session
    user_input = payload.message.strip()

    # ---------------- INIT ----------------
    if active_session["state"] == "INIT":
        # Start new session with all fields None except defaults
        session = {field: None for field in REQUIRED_FIELDS}
        session.update(DEFAULT_VALUES)

        active_session = {
            "state": "COLLECTING",
            "session": session,
            "current_field": REQUIRED_FIELDS[0]
        }

        return {"reply": "Type create supplier to begin."}

    state = active_session["state"]
    session = active_session.get("session")
    current_field = active_session.get("current_field")

    # ---------------- COLLECTING ----------------
    if state == "COLLECTING" and current_field:
        # Require user to type "create supplier" for the first field
        if current_field == REQUIRED_FIELDS[0] and user_input.lower() != "create supplier":
            return {"reply": 'Please type exactly: create supplier to begin.'}

        # Save the input for the current field (skip the first "create supplier" message)
        if current_field != REQUIRED_FIELDS[0] or user_input.lower() == "create supplier":
            if current_field != REQUIRED_FIELDS[0]:
                session[current_field] = user_input

            # Determine next missing field
            missing = get_missing_fields(session)
            if missing:
                next_field = missing[0]
                active_session["current_field"] = next_field
                active_session["session"] = session
                return {"reply": FIELD_QUESTIONS[next_field]}

            # All fields collected — validate
            errors = validate_against_fusion(session)
            if errors:
                # Map first error to a field
                error_text = errors[0]
                invalid_field = error_text.split(" ")[0]  # e.g., "TaxOrganizationType must be..."
                active_session["current_field"] = invalid_field
                return {"reply": f"{error_text}\n{FIELD_QUESTIONS.get(invalid_field, 'Please provide a valid value.')}"}

            # ---------------- CONFIRM ----------------
            summary = "\n".join(f"{f}: {session.get(f)}" for f in REQUIRED_FIELDS)
            active_session["state"] = "CONFIRM"
            active_session["session"] = session
            return {"reply": f"Please confirm supplier creation:\n\n{summary}\n\nType Yes, Edit, or Cancel."}

    # ---------------- CONFIRM ----------------
    if state == "CONFIRM":
        if user_input.lower() == "yes":
            status, response = create_supplier(session)
            active_session = {"state": "INIT"}
            if status == 201:
                return {
                    "reply": "Supplier created successfully.",
                    "data": {
                        "SupplierId": response.get("SupplierId"),
                        "SupplierNumber": response.get("SupplierNumber")
                    }
                }
            return {"reply": "Supplier creation failed. Please try again."}

        if user_input.lower() == "edit":
            active_session["state"] = "EDIT"
            return {
                "reply": "Select the field number to edit:\n" +
                         "\n".join(f"{i+1}. {f}" for i, f in enumerate(REQUIRED_FIELDS))
            }

        if user_input.lower() == "cancel":
            active_session = {"state": "INIT"}
            return {"reply": "Supplier creation cancelled. Type create supplier to begin again."}

        return {"reply": "Please respond with Yes, Edit, or Cancel."}

    # ---------------- EDIT ----------------
    if state == "EDIT":
        field_map = {str(i + 1): f for i, f in enumerate(REQUIRED_FIELDS)}
        if user_input in field_map:
            field = field_map[user_input]
            active_session["state"] = "COLLECTING"
            active_session["current_field"] = field
            return {"reply": FIELD_QUESTIONS[field]}
        return {"reply": "Invalid choice. Enter a valid number."}

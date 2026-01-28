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
def supplier_agent(
    payload: SupplierAgentRequest,
    username: str = Depends(authenticate_user)
):
    global active_session
    user_input = payload.message.strip().strip("{}")


    # -------------------------------------------------
    # INIT
    # -------------------------------------------------
    if active_session["state"] == "INIT":
        if "create supplier" not in user_input.lower():
            return {"reply": 'Type "create supplier" to begin.'}

        session = init_session()

        active_session = {
            "state": "COLLECTING",
            "session": session,
            "current_field": REQUIRED_FIELDS[0]
        }

        return {"reply": FIELD_QUESTIONS[REQUIRED_FIELDS[0]]}

    # -------------------------------------------------
    # LOAD STATE
    # -------------------------------------------------
    state = active_session["state"]
    session = active_session["session"]
    current_field = active_session.get("current_field")

    # -------------------------------------------------
    # COLLECTING MODE
    # -------------------------------------------------
    if state == "COLLECTING":

        # Save value for current field
        if current_field:
            session[current_field] = user_input

        # Find next missing field
        missing = get_missing_fields(session)

        if missing:
            next_field = missing[0]
            active_session["current_field"] = next_field
            return {"reply": FIELD_QUESTIONS[next_field]}

        # All fields collected → VALIDATE
        # Normalize all session values before validation
        for field in session:
            if isinstance(session[field], str):
                session[field] = session[field].strip().strip("{}")

        errors = validate_against_fusion(session)
        if errors:
            invalid_field = errors[0].split(" ")[0]
            active_session["current_field"] = invalid_field
            return {
                "reply": f"{errors[0]}\n{FIELD_QUESTIONS[invalid_field]}"
            }

        # Move to CONFIRM
        summary = "\n".join(
            f"{f}: {session.get(f)}" for f in REQUIRED_FIELDS
        )

        active_session["state"] = "CONFIRM"

        return {
            "reply": (
                "Please confirm supplier creation:\n\n"
                + summary +
                "\n\nType Yes, Edit, or Cancel."
            )
        }

    # -------------------------------------------------
    # CONFIRM MODE
    # -------------------------------------------------
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

            return {"reply": "Supplier creation failed."}

        if user_input.lower() == "edit":
            active_session["state"] = "EDIT"
            return {
                "reply": (
                    "Which field do you want to edit?\n" +
                    "\n".join(
                        f"{i+1}. {f}"
                        for i, f in enumerate(REQUIRED_FIELDS)
                    )
                )
            }

        if user_input.lower() == "cancel":
            active_session = {"state": "INIT"}
            return {"reply": "Supplier creation cancelled."}

        return {"reply": "Please respond with Yes, Edit, or Cancel."}

    # -------------------------------------------------
    # EDIT MODE
    # -------------------------------------------------
    if state == "EDIT":
        field_map = {
            str(i + 1): f
            for i, f in enumerate(REQUIRED_FIELDS)
        }

        if user_input in field_map:
            field = field_map[user_input]
            active_session["state"] = "COLLECTING"
            active_session["current_field"] = field
            return {"reply": FIELD_QUESTIONS[field]}

        return {"reply": "Invalid choice. Enter a valid field number."}

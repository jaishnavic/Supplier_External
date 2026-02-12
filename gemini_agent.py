from google import genai
from config.fusion_settings import GEMINI_API_KEY
import json
import logging
from google.genai.errors import ClientError

client = genai.Client(api_key=GEMINI_API_KEY)

SYSTEM_PROMPT = """
Extract Oracle Fusion Supplier fields from input.

Rules:
- Extract only explicitly mentioned fields
- Output JSON only
- No markdown
- No guessing

Fields:
Supplier
TaxOrganizationType
SupplierType
TaxpayerCountry
TaxpayerId
DUNSNumber
"""


def extract_supplier_payload(user_input: str) -> dict:
    try:
        response = client.models.generate_content(
            model="models/gemini-2.5-flash",
            contents=f"{SYSTEM_PROMPT}\n\nInput:\n{user_input}"
        )

        if not response or not response.text:
            return {}

        text = response.text.strip()

        if text.startswith("```"):
            text = text.replace("```json", "").replace("```", "").strip()

        parsed = json.loads(text)

        if isinstance(parsed, dict):
            return parsed

    except ClientError as e:
        logging.error(str(e))
    except Exception:
        logging.exception("Gemini extraction failed")

    return {}

import logging
import datetime
from db_mongo import get_col

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("noe")

def write_audit(action, username, spell_id, before, after):
    get_col("audit_logs").insert_one({
        "ts": datetime.datetime.utcnow().isoformat() + "Z",
        "user": username, "action": action, "spell_id": spell_id,
        "before": before, "after": after
    })

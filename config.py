import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

class Settings:
    PROJECT_NAME: str = "Trinity Health - Recall Management & Patient Safety Platform"
    VERSION: str = "2.0.0"
    HOST: str = "0.0.0.0"
    PORT: int = int(os.getenv("PORT", "8010"))
    
    # Session & Security
    SESSION_SECRET_KEY: str = os.getenv("SESSION_SECRET_KEY", "trinity-health-recall-hub-secret-2026")
    DEMO_USER: str = os.getenv("DEMO_USER", "trinity.admin@trinity-health.org")
    DEMO_PASS: str = os.getenv("DEMO_PASS", "Trinity2026!")
    
    # Data paths - checks local data dir first, falls back to Cardinal Health if present
    LOCAL_DATA_DIR: Path = BASE_DIR / "data"
    CARDINAL_DATA_DIR: Path = BASE_DIR.parent / "cardinal_mosaic" / "data"
    
    _default_feather = LOCAL_DATA_DIR / "preprocessed_alerts.feather" if (LOCAL_DATA_DIR / "preprocessed_alerts.feather").exists() else (CARDINAL_DATA_DIR / "preprocessed_alerts.feather")
    _default_fda = LOCAL_DATA_DIR / "fda_events_lookup.json" if (LOCAL_DATA_DIR / "fda_events_lookup.json").exists() else (CARDINAL_DATA_DIR / "fda_events_lookup.json")
    
    FEATHER_PATH: Path = Path(os.getenv("FEATHER_PATH", str(_default_feather)))
    FDA_LOOKUP_PATH: Path = Path(os.getenv("FDA_LOOKUP_PATH", str(_default_fda)))
    
    # Local data store for audit logs and actions
    LOCAL_DATA_DIR: Path = BASE_DIR / "data"
    ACTIONS_LOG_PATH: Path = LOCAL_DATA_DIR / "actions_log.json"

    # Atlassian Jira Cloud Integration
    JIRA_BASE_URL: str = os.getenv("JIRA_BASE_URL", "https://supplycopia.atlassian.net")
    JIRA_PROJECT_KEY: str = os.getenv("JIRA_PROJECT_KEY", "TRM")
    JIRA_BOARD_ID: str = os.getenv("JIRA_BOARD_ID", "497")
    JIRA_USER_EMAIL: str = os.getenv("JIRA_USER_EMAIL", "nrayan@supplycopia.com")
    JIRA_API_TOKEN: str = os.getenv("JIRA_API_TOKEN", "")

    # OpenAI Configuration for Clinical Memos & Incident AI
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    # GitHub Repository Configuration
    GITHUB_REPO_URL: str = os.getenv("GITHUB_REPO_URL", "https://github.com/supplycopia-nirmal/trinity-recall.git")
    GITHUB_PAT: str = os.getenv("GITHUB_PAT", "")

settings = Settings()

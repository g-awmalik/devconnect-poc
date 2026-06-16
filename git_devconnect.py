import os
import subprocess
import requests
import argparse
import google.auth
from google.auth.transport.requests import Request

# ==========================================
# CONFIGURATION VARIABLES
# ==========================================
PROJECT_ID = "your-gcp-project-id"
LOCATION = "us-central1"               # Region where DevConnect is configured
CONNECTION_NAME = "my-github-conn"     # Name of your Developer Connect Connection
REPO_LINK_NAME = "my-repo-link"        # Name of the GitRepositoryLink in DevConnect

GITHUB_OWNER = "your-github-org"       # e.g., "octocat"
GITHUB_REPO = "your-repo-name"         # e.g., "hello-world"
TARGET_BRANCH = "main"                 # Or the specific PR branch name

CLONE_DIR = "/tmp/my_repo_workspace"

# ==========================================
# HELPER FUNCTIONS
# ==========================================
def get_gcp_access_token():
    """Fetches the ADC token from the GCE VM's Metadata Server."""
    print("🔑 Fetching GCP credentials from VM metadata...")
    credentials, _ = google.auth.default()
    credentials.refresh(Request())
    return credentials.token

def fetch_devconnect_token(gcp_token):
    """Calls Developer Connect API to get a short-lived GitHub Read/Write token."""
    print("🌐 Requesting short-lived GitHub token from Developer Connect...")
    url = (
        f"https://developerconnect.googleapis.com/v1/"
        f"projects/{PROJECT_ID}/locations/{LOCATION}/"
        f"connections/{CONNECTION_NAME}/gitRepositoryLinks/{REPO_LINK_NAME}:fetchReadWriteToken"
    )
    headers = {
        "Authorization": f"Bearer {gcp_token}",
        "Content-Type": "application/json"
    }
    response = requests.post(url, headers=headers)
    
    if response.status_code != 200:
        raise Exception(f"Failed to fetch token: {response.status_code} - {response.text}")
    
    return response.json().get("token")

def get_authenticated_repo_url():
    """Fetches a fresh token and returns the HTTPS OAuth2 Git URL."""
    gcp_token = get_gcp_access_token()
    github_token = fetch_devconnect_token(gcp_token)
    return f"https://oauth2:{github_token}@github.com/{GITHUB_OWNER}/{GITHUB_REPO}.git"

def run_cmd(cmd, cwd=None):
    """Executes a shell command and streams the output."""
    print(f"🚀 Running: {' '.join(cmd)}")
    subprocess.check_call(cmd, cwd=cwd)

# ==========================================
# CORE ACTIONS
# ==========================================
def action_clone():
    print("--- STARTING CLONE OPERATION ---")
    auth_repo_url = get_authenticated_repo_url()

    # Clean up previous runs
    if os.path.exists(CLONE_DIR):
        print(f"🧹 Cleaning up existing directory at {CLONE_DIR}...")
        run_cmd(["rm", "-rf", CLONE_DIR])

    # Clone the repository
    print(f"📥 Cloning branch '{TARGET_BRANCH}'...")
    run_cmd(["git", "clone", "--branch", TARGET_BRANCH, auth_repo_url, CLONE_DIR])

    # Configure Git Identity for the VM locally
    print("⚙️ Configuring Git identity...")
    run_cmd(["git", "config", "user.name", "Autocloud Agent"], cwd=CLONE_DIR)
    run_cmd(["git", "config", "user.email", "agent@autocloud.local"], cwd=CLONE_DIR)
    print("✅ Clone complete!\n")


def action_push(commit_message):
    print("--- STARTING PUSH OPERATION ---")
    if not os.path.exists(CLONE_DIR):
        raise FileNotFoundError(f"Clone directory {CLONE_DIR} does not exist. Run clone first.")

    # 1. Fetch a FRESH token (in case the assessment took longer than 1 hour)
    auth_repo_url = get_authenticated_repo_url()

    # 2. Update the remote origin to use the new token
    print("🔄 Updating Git remote with fresh authentication token...")
    run_cmd(["git", "remote", "set-url", "origin", auth_repo_url], cwd=CLONE_DIR)

    # 3. Add files and check for diffs
    print("📝 Staging changes...")
    run_cmd(["git", "add", "."], cwd=CLONE_DIR)
    status = subprocess.run(["git", "status", "--porcelain"], cwd=CLONE_DIR, capture_output=True, text=True)
    
    if not status.stdout.strip():
        print("🤷 No changes detected in the workspace. Exiting without pushing.")
        return

    # 4. Commit and Push
    print("📤 Committing and Pushing to GitHub...")
    run_cmd(["git", "commit", "-m", commit_message], cwd=CLONE_DIR)
    run_cmd(["git", "push", "origin", TARGET_BRANCH], cwd=CLONE_DIR)
    
    print("🎉 Success! Remediations pushed to GitHub via Developer Connect.\n")

# ==========================================
# MAIN ENTRY POINT
# ==========================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Autocloud Agent Git Operations via DevConnect")
    parser.add_argument(
        "action", 
        choices=["clone", "push"], 
        help="The Git action to perform."
    )
    parser.add_argument(
        "--message", 
        default="chore: Automated remediation by Autocloud\n\nSee execution logs for report details.",
        help="The commit message (only used for the 'push' action)."
    )
    
    args = parser.parse_args()

    try:
        if args.action == "clone":
            action_clone()
        elif args.action == "push":
            action_push(args.message)
    except Exception as e:
        print(f"\n❌ Error during {args.action} execution: {e}")
        exit(1)

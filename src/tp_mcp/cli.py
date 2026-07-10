"""CLI commands for TrainingPeaks MCP Server."""

import getpass
import sys

from tp_mcp.auth import (
    AuthStatus,
    clear_credential,
    get_credential,
    get_storage_backend,
    is_keyring_available,
    store_credential,
    validate_auth_sync,
)
from tp_mcp.auth.browser import extract_tp_cookie


def cmd_auth(from_browser: str | None = None) -> int:
    """Interactive authentication flow.

    Args:
        from_browser: Browser to extract cookie from (chrome, firefox, etc.)
                      If None, prompts for manual cookie input.

    Returns:
        Exit code (0 for success, 1 for failure).
    """
    print("TrainingPeaks MCP Authentication")
    print("=" * 40)
    print()

    # Check if keyring is available
    if not is_keyring_available():
        print("Warning: No system keyring available.")
        print("Cookie will be stored in an encrypted file.")
        print()

    # Check for existing credential
    existing = get_credential()
    if existing.success and existing.cookie:
        print("Existing credential found. Validating...")
        result = validate_auth_sync(existing.cookie)
        if result.is_valid:
            print(f"Already authenticated as: {result.email}")
            print(f"Athlete ID: {result.athlete_id}")
            print()
            if not from_browser:
                response = input("Re-authenticate? [y/N]: ").strip().lower()
                if response != "y":
                    return 0

    # Get cookie from browser or manual input
    if from_browser:
        print(f"Extracting cookie from {from_browser}...")
        browser_result = extract_tp_cookie(from_browser if from_browser != "auto" else None)
        if not browser_result.success:
            print(f"Error: {browser_result.message}")
            return 1
        cookie = browser_result.cookie
        print(f"Found cookie in {browser_result.browser}")
    else:
        print()
        print("To authenticate, you need the Production_tpAuth cookie from TrainingPeaks.")
        print()
        print("Steps:")
        print("1. Log into TrainingPeaks in your browser")
        print("2. Go to app.trainingpeaks.com")
        print("3. Open DevTools (F12) -> Application tab -> Cookies")
        print("4. Find 'Production_tpAuth' cookie")
        print("5. Copy the cookie value")
        print()
        print("Or use: tp-mcp auth --from-browser chrome")
        print()

        # Get cookie from user (use getpass to hide input)
        try:
            cookie = getpass.getpass("Paste cookie value (hidden): ")
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled.")
            return 1

        if not cookie.strip():
            print("Error: No cookie provided.")
            return 1

    print()
    print("Validating...")

    # Validate the cookie
    result = validate_auth_sync(cookie)

    if not result.is_valid:
        print(f"Error: {result.message}")
        if result.status == AuthStatus.EXPIRED:
            print("The cookie may have expired. Please get a fresh cookie.")
        elif result.status == AuthStatus.INVALID:
            print("The cookie appears to be invalid. Check that you copied it correctly.")
        return 1

    # Store the credential
    store_result = store_credential(cookie)
    if not store_result.success:
        print(f"Error storing credential: {store_result.message}")
        return 1

    print()
    print("Authentication successful!")
    print(f"  Email: {result.email}")
    print(f"  Athlete ID: {result.athlete_id}")
    print()
    print("You can now use 'tp-mcp serve' to start the MCP server.")

    return 0


def cmd_auth_status() -> int:
    """Check current authentication status.

    Returns:
        Exit code (0 for authenticated, 1 for not authenticated).
    """
    cred = get_credential()
    if not cred.success or not cred.cookie:
        print("Not authenticated.")
        print("Run 'tp-mcp auth' to authenticate.")
        return 1

    print("Checking authentication status...")
    result = validate_auth_sync(cred.cookie)

    if result.is_valid:
        print("Authenticated")
        print(f"  Email: {result.email}")
        print(f"  Athlete ID: {result.athlete_id}")
        print(f"  Storage: {get_storage_backend()}")
        return 0
    else:
        print(f"Authentication invalid: {result.message}")
        print("Run 'tp-mcp auth' to re-authenticate.")
        return 1


def cmd_auth_clear() -> int:
    """Clear stored credentials.

    Returns:
        Exit code (0 for success).
    """
    result = clear_credential()
    if result.success:
        print("Credentials cleared.")
    else:
        print(f"Note: {result.message}")
    return 0


def cmd_serve(transport: str = "stdio", host: str = "127.0.0.1", port: int = 8000) -> int:
    """Start the MCP server.

    Args:
        transport: Transport to use ("stdio" or "http").
        host: Host to bind to (http transport only).
        port: Port to bind to (http transport only).

    Returns:
        Exit code.
    """
    if transport == "stdio":
        from tp_mcp.server import run_server

        return run_server()

    import os

    from tp_mcp.http_app import AUTH_SECRET_ENV, create_app

    secret = os.environ.get(AUTH_SECRET_ENV)
    if not secret and host not in ("127.0.0.1", "localhost", "::1"):
        print(f"Error: {AUTH_SECRET_ENV} must be set to serve on a non-local host ({host}).")
        return 1

    app = create_app(require_auth=bool(secret))
    if not secret:
        print(f"Warning: {AUTH_SECRET_ENV} not set. Serving unauthenticated on {host}:{port}.")

    import uvicorn

    uvicorn.run(app, host=host, port=port)
    return 0


def cmd_push_cookie(
    from_browser: str | None = None, from_stored: bool = False, target: str = "production"
) -> int:
    """Push a TrainingPeaks cookie to Vercel from a browser or the local store.

    Args:
        from_browser: Browser to extract cookie from (chrome, firefox, etc.).
                      Defaults to "chrome" when neither source is specified.
        from_stored: Read the cookie from the local credential store instead of a browser.
        target: Vercel environment to push to (production, preview, development).

    Returns:
        Exit code (0 for success, 1 for failure).
    """
    import shutil
    import subprocess

    if from_stored:
        # Cookie was already stored by 'tp-mcp auth', so don't re-store it below.
        cred = get_credential()
        if not cred.success or not cred.cookie:
            print(f"Error: {cred.message}")
            print("No stored credential found. Run 'tp-mcp auth' first to paste a cookie.")
            return 1
        cookie = cred.cookie
        print("Using stored credential.")
    else:
        browser = from_browser or "chrome"
        print(f"Extracting cookie from {browser}...")
        browser_result = extract_tp_cookie(browser if browser != "auto" else None)
        if not browser_result.success or not browser_result.cookie:
            print(f"Error: {browser_result.message}")
            print()
            print("macOS may be blocking browser cookie access (Full Disk Access required for your")
            print("terminal: System Settings > Privacy & Security > Full Disk Access).")
            print("Alternative that needs no browser access: run 'tp-mcp auth' to paste the cookie,")
            print("then 'tp-mcp push-cookie --from-stored'.")
            return 1
        cookie = browser_result.cookie
        print(f"Found cookie in {browser_result.browser}")

    print("Validating...")
    result = validate_auth_sync(cookie)
    if not result.is_valid:
        print(f"Error: {result.message}")
        print("Aborting: refusing to push an invalid cookie.")
        return 1
    print("Cookie is valid.")
    print(f"  Email: {result.email}")
    print(f"  Athlete ID: {result.athlete_id}")

    # Keep local stdio credentials in sync when extracted from a browser.
    if not from_stored:
        store_result = store_credential(cookie)
        if not store_result.success:
            print(f"Warning: could not update local credential: {store_result.message}")

    if not shutil.which("vercel"):
        print("Error: vercel CLI not found. Install it with: npm i -g vercel")
        return 1

    print(f"Pushing cookie to Vercel ({target})...")
    # Nonzero here just means the var doesn't exist yet on first push; ignore it.
    subprocess.run(["vercel", "env", "rm", "TP_AUTH_COOKIE", target, "-y"], capture_output=True)

    add_result = subprocess.run(
        ["vercel", "env", "add", "TP_AUTH_COOKIE", target],
        input=cookie,
        text=True,
        capture_output=True,
    )
    if add_result.returncode != 0:
        print("Error: failed to push cookie to Vercel.")
        print(add_result.stderr)  # vercel CLI stderr never contains the cookie
        return 1

    if target == "production":
        print("Redeploying to bake in the new cookie...")
        # 'vercel deploy' rather than 'vercel redeploy': the latter needs an existing
        # deployment URL, so it cannot run before the project's first deployment.
        redeploy_result = subprocess.run(["vercel", "deploy", "--prod", "--yes"], capture_output=True, text=True)
        if redeploy_result.returncode != 0:
            print("Error: redeploy failed.")
            print(redeploy_result.stderr)
            return 1
    else:
        print(f"Note: skipping redeploy for non-production target '{target}'.")

    print("Done.")
    return 0


def cmd_schedule() -> int:
    """Print a launchd plist that runs 'push-cookie' weekly.

    Returns:
        Exit code (0).
    """
    import shutil
    from pathlib import Path

    tp_mcp_path = shutil.which("tp-mcp")
    if not tp_mcp_path:
        # Fall back to sys.executable directory
        tp_mcp_path = str(Path(sys.executable).parent / "tp-mcp")

    plist_path = "~/Library/LaunchAgents/com.trainingpeaks-mcp.refresh.plist"

    print("Weekly cookie refresh via launchd", file=sys.stderr)
    print("=" * 40, file=sys.stderr)
    print(file=sys.stderr)
    print("Save the plist below, then load it:", file=sys.stderr)
    print(f"  tp-mcp schedule > {plist_path}", file=sys.stderr)
    print(f"  launchctl load {plist_path}", file=sys.stderr)
    print(file=sys.stderr)

    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.trainingpeaks-mcp.refresh</string>
    <key>ProgramArguments</key>
    <array>
        <string>{tp_mcp_path}</string>
        <string>push-cookie</string>
        <string>--from-browser</string>
        <string>chrome</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Weekday</key>
        <integer>1</integer>
        <key>Hour</key>
        <integer>9</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>/tmp/tp-mcp-refresh.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/tp-mcp-refresh.log</string>
</dict>
</plist>"""
    print(plist)

    print(file=sys.stderr)
    print("If the weekly job ever fails (e.g. the browser got logged out), just run", file=sys.stderr)
    print("'tp-mcp push-cookie' manually to refresh it by hand.", file=sys.stderr)

    return 0


def cmd_config() -> int:
    """Output Claude Desktop config snippet.

    Returns:
        Exit code (0).
    """
    import json
    import shutil

    # Find the tp-mcp binary path
    tp_mcp_path = shutil.which("tp-mcp")
    if not tp_mcp_path:
        # Fall back to sys.executable directory
        from pathlib import Path
        tp_mcp_path = str(Path(sys.executable).parent / "tp-mcp")

    config = {
        "trainingpeaks": {
            "command": tp_mcp_path,
            "args": ["serve"]
        }
    }

    print("Add this to your Claude Desktop config inside \"mcpServers\": {}")
    print()
    print(json.dumps(config, indent=2))
    return 0


def cmd_help() -> int:
    """Show help message.

    Returns:
        Exit code (0).
    """
    print("TrainingPeaks MCP Server")
    print()
    print("Usage: tp-mcp <command> [options]")
    print()
    print("Commands:")
    print("  auth                  Authenticate with TrainingPeaks")
    print("    --from-browser X    Extract cookie from browser (chrome, firefox, safari, edge, auto)")
    print("  auth-status           Check authentication status")
    print("  auth-clear            Clear stored cookie")
    print("  config                Output Claude Desktop config snippet")
    print("  serve                 Start the MCP server")
    print("    --transport X      Transport to use: stdio (default) or http")
    print("    --host X           Host to bind to for http transport (default 127.0.0.1)")
    print("    --port X           Port to bind to for http transport (default 8000)")
    print("  push-cookie           Refresh the TrainingPeaks cookie and push it to Vercel")
    print("    --from-browser X   Extract cookie from browser (chrome, firefox, safari, edge, auto)")
    print("    --from-stored      Use the cookie from 'tp-mcp auth' (no browser access; avoids the")
    print("                       macOS Full Disk Access requirement for reading browser cookies)")
    print("    --target X         Vercel environment to push to (default production)")
    print("  schedule              Print a launchd plist that runs push-cookie weekly")
    print("  help                  Show this help message")
    print()
    print("Examples:")
    print("  tp-mcp auth                      # Manual cookie entry")
    print("  tp-mcp auth --from-browser auto  # Auto-detect browser")
    print("  tp-mcp auth --from-browser chrome")
    print("  tp-mcp serve --transport http --port 8000")
    print("  tp-mcp push-cookie --from-browser chrome")
    print("  tp-mcp schedule > ~/Library/LaunchAgents/com.trainingpeaks-mcp.refresh.plist")
    print()
    return 0


def main() -> int:
    """Main CLI entry point.

    Returns:
        Exit code.
    """
    if len(sys.argv) < 2:
        return cmd_help()

    command = sys.argv[1].lower()

    # Handle auth command with optional --from-browser flag
    if command == "auth":
        from_browser = None
        args = sys.argv[2:]
        if "--from-browser" in args:
            idx = args.index("--from-browser")
            if idx + 1 < len(args):
                from_browser = args[idx + 1]
            else:
                print("Error: --from-browser requires a browser name (chrome, firefox, auto, etc.)")
                return 1
        return cmd_auth(from_browser=from_browser)

    # Handle serve command with optional --transport/--host/--port flags
    if command == "serve":
        args = sys.argv[2:]
        transport = "stdio"
        host = "127.0.0.1"
        port = 8000
        if "--transport" in args:
            idx = args.index("--transport")
            if idx + 1 < len(args):
                transport = args[idx + 1]
            else:
                print("Error: --transport requires a value (stdio or http)")
                return 1
        if transport not in ("stdio", "http"):
            print(f"Error: invalid transport '{transport}' (expected stdio or http)")
            return 1
        if "--host" in args:
            idx = args.index("--host")
            if idx + 1 < len(args):
                host = args[idx + 1]
            else:
                print("Error: --host requires a value")
                return 1
        if "--port" in args:
            idx = args.index("--port")
            if idx + 1 < len(args):
                try:
                    port = int(args[idx + 1])
                except ValueError:
                    print("Error: --port requires an integer value")
                    return 1
            else:
                print("Error: --port requires a value")
                return 1
        return cmd_serve(transport=transport, host=host, port=port)

    # Handle push-cookie command with optional --from-browser/--from-stored/--target flags
    if command == "push-cookie":
        args = sys.argv[2:]
        from_browser = None
        from_stored = "--from-stored" in args
        target = "production"
        if "--from-browser" in args:
            idx = args.index("--from-browser")
            if idx + 1 < len(args):
                from_browser = args[idx + 1]
            else:
                print("Error: --from-browser requires a browser name (chrome, firefox, auto, etc.)")
                return 1
        if from_browser is not None and from_stored:
            print("Error: --from-browser and --from-stored are mutually exclusive.")
            return 1
        if "--target" in args:
            idx = args.index("--target")
            if idx + 1 < len(args):
                target = args[idx + 1]
            else:
                print("Error: --target requires a value (e.g. production, preview)")
                return 1
        return cmd_push_cookie(from_browser=from_browser, from_stored=from_stored, target=target)

    commands = {
        "auth-status": cmd_auth_status,
        "auth-clear": cmd_auth_clear,
        "config": cmd_config,
        "schedule": cmd_schedule,
        "help": cmd_help,
        "--help": cmd_help,
        "-h": cmd_help,
    }

    if command in commands:
        return commands[command]()
    else:
        print(f"Unknown command: {command}")
        print("Run 'tp-mcp help' for usage.")
        return 1

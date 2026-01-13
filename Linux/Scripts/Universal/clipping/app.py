from flask import Flask, jsonify
import subprocess

app = Flask(__name__)

def is_shadowplay_running():
    """
    Check if shadowplay.sh is running by looking for it in the process list.
    Returns True if running, False otherwise.
    """
    try:
        # Check if shadowplay.sh is running (same logic as instant-shadowplay-checker.sh)
        result = subprocess.run(
            "ps aux | grep shadowplay.sh | grep -v grep",
            shell=True,
            capture_output=True,
            text=True
        )
        # If returncode is 0, shadowplay.sh was found in process list
        return result.returncode == 0
    except Exception:
        return False

@app.route('/clip', methods=['POST'])
def clip():
    """
    API endpoint to send a SIGUSR1 signal to gpu-screen-recorder
    and send a desktop notification.
    """
    # First check if shadowplay.sh is running
    if not is_shadowplay_running():
        # Send notification that shadowplay is not running (like instant-shadowplay-checker.sh)
        try:
            subprocess.run(
                'notify-send --icon ~/LOGO.png -a "Nvidia" "Shadowplay" "shadowplay.sh is not running"',
                shell=True,
                check=True
            )
        except Exception:
            pass  # Don't fail the response if notification fails
        
        return jsonify({
            "success": False,
            "message": "shadowplay.sh is not running",
            "results": []
        }), 400

    commands = [
        "pkill -SIGUSR1 -f gpu-screen-recorder",
        'notify-send --icon ~/LOGO.png -a "Nvidia Shadowplay" "#Clipped" "Clip saved successfully"'
    ]

    results = []
    overall_success = True

    for command in commands:
        try:
            # Execute the command
            process = subprocess.run(
                command,
                shell=True,
                check=True,  # Raise an exception for non-zero exit codes
                capture_output=True, # Capture stdout and stderr
                text=True # Decode stdout/stderr as text
            )
            results.append({
                "command": command,
                "success": True,
                "message": "Executed successfully",
                "stdout": process.stdout,
                "stderr": process.stderr
            })
        except subprocess.CalledProcessError as e:
            overall_success = False
            results.append({
                "command": command,
                "success": False,
                "message": f"Error executing command: {e}",
                "stdout": e.stdout,
                "stderr": e.stderr
            })
        except Exception as e:
            overall_success = False
            results.append({
                "command": command,
                "success": False,
                "message": f"An unexpected error occurred: {str(e)}",
                "stdout": "",
                "stderr": str(e) # In case of non-subprocess error, stderr might be just the error message
            })

    if overall_success:
        return jsonify({
            "success": True,
            "message": "All commands executed successfully.",
            "results": results
        })
    else:
        return jsonify({
            "success": False,
            "message": "One or more commands failed to execute.",
            "results": results
        }), 500 # Internal Server Error if any command fails

if __name__ == '__main__':
    app.run(port=7328)
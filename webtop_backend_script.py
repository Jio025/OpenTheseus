"""Webtop backend API tool for webtop functionality on Theseus"""
# For API functionality
from flask import Flask, request, jsonify
# For remove and chmod
import os
# For running bash scripts
import subprocess
# For final constant warnings
from typing import Final
# For secure filenames
from werkzeug.utils import secure_filename
# For regex pattern matching
import re
# For traceback
import traceback

app = Flask(__name__)

# Constants
RUN_FILE: Final[str] = "run.sh"
SERVER_URL: Final[str] = "http://127.0.0.1:80"
UPLOAD_DIR = "/opt/webtops/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


# ============================================
# HELPER FUNCTIONS
# ============================================

def create_run_sh_file(yaml_filename: str) -> int:
    """Create a run.sh file that runs the given Docker Compose YAML file."""
    try:
        with open(RUN_FILE, "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\n")
            f.write(f"# Script utilisé pour exécuter l'image {yaml_filename} dans le conteneur {yaml_filename}\n")
            f.write(f"docker compose -f {yaml_filename}.yml up\n")
        os.chmod(RUN_FILE, 0o755)
        return 0
    except Exception as e:
        print(f"Error creating run.sh: {e}")
        return 1


def delete_run_sh_file() -> int:
    """Delete the run.sh file if it exists."""
    try:
        os.remove(RUN_FILE)
        return 0
    except FileNotFoundError:
        return 1
    except Exception as e:
        print(f"Error deleting run.sh: {e}")
        return 2


def run_run_sh_file() -> int:
    """Runs the run.sh file locally"""
    try:
        result = subprocess.run(['./run.sh'],
                                capture_output=True, text=True, check=True)
        print("Script output:")
        print(result.stdout)
        if result.stderr:
            print("Script errors:")
            print(result.stderr)
            return 1
        return 0
    except subprocess.CalledProcessError as e:
        print(f"Error running script: {e}")
        print(f"Stderr: {e.stderr}")
        return 1


def extract_user_from_yaml(yaml_file):
    """
    Helper function to extract user ID from YAML content
    Looks for container_name: webtop-ubuntu-xfce-<user>
    """
    try:
        yaml_file.seek(0)  # Reset file pointer
        content = yaml_file.read().decode('utf-8')
        yaml_file.seek(0)  # Reset again for saving

        match = re.search(r'container_name:\s*webtop-ubuntu-xfce-(\w+)', content)
        if match:
            return match.group(1)
    except Exception as e:
        print(f"Error extracting user from YAML: {e}")
    return None


def extract_port_from_yaml(yaml_file):
    """
    Helper function to extract port from YAML content
    Looks for port mapping like "3021:3000"
    """
    try:
        yaml_file.seek(0)  # Reset file pointer
        content = yaml_file.read().decode('utf-8')
        yaml_file.seek(0)  # Reset again for saving

        match = re.search(r'-\s*(\d+):3000', content)
        if match:
            return int(match.group(1))
    except Exception as e:
        print(f"Error extracting port from YAML: {e}")
    return None


# ============================================
# API ENDPOINTS
# ============================================

@app.route("/", methods=["GET"])
def index():
    """Simple health check."""
    return jsonify({
        "status": "ok",
        "message": "Webtop API is active",
        "version": "1.0.0",
        "endpoints": {
            "GET /": "Health check",
            "POST /deploy": "Deploy a new webtop instance",
            "GET /deploy/status/<webtop_id>": "Check webtop status",
            "POST /deploy/stop/<webtop_id>": "Stop a webtop instance",
            "DELETE /deploy/cleanup/<webtop_id>": "Cleanup webtop files"
        }
    }), 200


@app.route("/deploy", methods=["POST"])
def deploy_webtop():
    """
    Endpoint compatible with Java JAX-RS multipart form-data
    Accepts:
    - docker-compose: YAML file
    - dockerfile-1, dockerfile-2, ...: Multiple Dockerfiles
    - resource-1, resource-2, ...: Multiple resource files
    """
    webtop_id = None
    webtop_dir = None

    try:
        # Extract all files from the request
        files = request.files

        if not files:
            return jsonify({
                "status": "error",
                "message": "No files received"
            }), 400

        # === Extract docker-compose YAML ===
        yaml_file = files.get("docker-compose")
        if not yaml_file:
            return jsonify({
                "status": "error",
                "message": "Missing docker-compose file"
            }), 400

        # Parse the YAML filename
        yaml_filename = secure_filename(yaml_file.filename or "docker-compose.yaml")

        # Extract user ID and port from YAML content
        webtop_id = extract_user_from_yaml(yaml_file)
        port = extract_port_from_yaml(yaml_file)

        if not webtop_id:
            webtop_id = "default_user"
            print("Warning: Could not extract user ID from YAML, using default")

        # Create webtop directory
        webtop_dir = os.path.join(UPLOAD_DIR, f"webtop_{webtop_id}")
        os.makedirs(webtop_dir, exist_ok=True)
        print(f"Created/verified webtop directory: {webtop_dir}")

        # === Save docker-compose YAML ===
        yaml_path = os.path.join(webtop_dir, yaml_filename)
        yaml_file.save(yaml_path)
        print(f"Saved YAML file: {yaml_path}")

        saved_files = {
            "yaml": yaml_filename,
            "dockerfiles": [],
            "resources": []
        }

        # === Save all Dockerfiles ===
        # Java sends as: dockerfile-1, dockerfile-2, etc.
        dockerfile_count = 0
        for key in sorted(files.keys()):
            if key.startswith("dockerfile-"):
                dockerfile = files[key]
                dockerfile_name = secure_filename(dockerfile.filename or f"Dockerfile.{dockerfile_count + 1}")
                dockerfile_path = os.path.join(webtop_dir, dockerfile_name)
                dockerfile.save(dockerfile_path)
                saved_files["dockerfiles"].append(dockerfile_name)
                dockerfile_count += 1
                print(f"Saved Dockerfile: {dockerfile_name}")

        # === Save all Resources ===
        # Java sends as: resource-1, resource-2, etc.
        resource_count = 0
        for key in sorted(files.keys()):
            if key.startswith("resource-"):
                resource = files[key]
                resource_name = secure_filename(resource.filename or f"resource_{resource_count + 1}")
                resource_path = os.path.join(webtop_dir, resource_name)
                resource.save(resource_path)
                saved_files["resources"].append(resource_name)
                resource_count += 1
                print(f"Saved resource: {resource_name}")

        # === Create run.sh script ===
        run_sh_path = os.path.join(webtop_dir, "run.sh")
        with open(run_sh_path, "w", encoding="utf-8") as f:
            f.write("#!/bin/bash\n")
            f.write(f"# Webtop deployment script for user: {webtop_id}\n")
            f.write(f"# Generated automatically by Webtop API\n\n")
            f.write(f"cd {webtop_dir}\n\n")

            # Build Dockerfiles if present
            if saved_files["dockerfiles"]:
                f.write("# Build custom Docker images\n")
                for i, dockerfile in enumerate(saved_files["dockerfiles"], 1):
                    image_tag = f"webtop-custom-{webtop_id}-{i}"
                    f.write(f"echo 'Building Docker image: {image_tag}'\n")
                    f.write(f"docker build -f {dockerfile} -t {image_tag} .\n")
                    f.write(f"if [ $? -ne 0 ]; then\n")
                    f.write(f"    echo 'Error: Failed to build {image_tag}'\n")
                    f.write(f"    exit 1\n")
                    f.write(f"fi\n\n")

            # Launch docker compose
            f.write("# Launch Docker Compose\n")
            f.write(f"echo 'Starting Docker Compose with {yaml_filename}'\n")
            f.write(f"docker compose -f {yaml_filename} up -d\n")
            f.write(f"if [ $? -eq 0 ]; then\n")
            f.write(f"    echo 'Webtop deployment successful for user: {webtop_id}'\n")
            f.write(f"else\n")
            f.write(f"    echo 'Error: Docker Compose failed'\n")
            f.write(f"    exit 1\n")
            f.write(f"fi\n")

        os.chmod(run_sh_path, 0o755)
        print(f"Created run.sh script: {run_sh_path}")

        # === Execute deployment asynchronously ===
        print(f"Launching deployment for user: {webtop_id}")
        process = subprocess.Popen(
            ["bash", run_sh_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=webtop_dir
        )

        # Prepare response
        response_data = {
            "status": "success",
            "message": f"Webtop deployment initiated for user: {webtop_id}",
            "webtop_dir": webtop_dir,
            "webtop_id": webtop_id,
            "port": port,
            "files": saved_files,
            "process_id": process.pid,
            "container_name": f"webtop-ubuntu-xfce-{webtop_id}"
        }

        print(f"Deployment response: {response_data}")
        return jsonify(response_data), 200

    except Exception as e:
        error_trace = traceback.format_exc()
        print(f"Error in deploy_webtop: {error_trace}")
        return jsonify({
            "status": "error",
            "message": str(e),
            "webtop_id": webtop_id,
            "webtop_dir": webtop_dir,
            "traceback": error_trace
        }), 500


@app.route("/deploy/status/<webtop_id>", methods=["GET"])
def check_webtop_status(webtop_id):
    """
    Check if a webtop deployment is running
    """
    try:
        # Check if container is running
        result = subprocess.run(
            ["docker", "ps", "--filter", f"name=webtop-ubuntu-xfce-{webtop_id}", "--format", "{{.Names}}"],
            capture_output=True,
            text=True
        )

        container_name = result.stdout.strip()

        if container_name:
            # Get additional container info
            inspect_result = subprocess.run(
                ["docker", "inspect", container_name, "--format", "{{.State.Status}}"],
                capture_output=True,
                text=True
            )
            container_status = inspect_result.stdout.strip()

            # Get port mapping
            port_result = subprocess.run(
                ["docker", "port", container_name],
                capture_output=True,
                text=True
            )

            return jsonify({
                "status": "running",
                "container": container_name,
                "container_status": container_status,
                "webtop_id": webtop_id,
                "ports": port_result.stdout.strip()
            }), 200
        else:
            return jsonify({
                "status": "not_running",
                "webtop_id": webtop_id,
                "message": "Container not found or stopped"
            }), 200

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e),
            "webtop_id": webtop_id
        }), 500


@app.route("/deploy/stop/<webtop_id>", methods=["POST"])
def stop_webtop(webtop_id):
    """
    Stop a running webtop container
    """
    try:
        webtop_dir = os.path.join(UPLOAD_DIR, f"webtop_{webtop_id}")
        yaml_path = os.path.join(webtop_dir, "docker-compose.yaml")

        if not os.path.exists(webtop_dir):
            return jsonify({
                "status": "error",
                "message": f"Webtop directory not found: {webtop_id}"
            }), 404

        # Try to find any yaml file in the directory
        yaml_files = [f for f in os.listdir(webtop_dir) if f.endswith(('.yaml', '.yml'))]
        if yaml_files:
            yaml_path = os.path.join(webtop_dir, yaml_files[0])
        else:
            return jsonify({
                "status": "error",
                "message": f"No YAML file found in webtop directory: {webtop_id}"
            }), 404

        print(f"Stopping webtop {webtop_id} using {yaml_path}")

        result = subprocess.run(
            ["docker", "compose", "-f", yaml_path, "down"],
            capture_output=True,
            text=True,
            cwd=webtop_dir
        )

        if result.returncode == 0:
            return jsonify({
                "status": "success",
                "message": f"Webtop stopped: {webtop_id}",
                "output": result.stdout,
                "webtop_dir": webtop_dir
            }), 200
        else:
            return jsonify({
                "status": "error",
                "message": "Failed to stop webtop",
                "error": result.stderr,
                "webtop_id": webtop_id
            }), 500

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e),
            "webtop_id": webtop_id
        }), 500


@app.route("/deploy/cleanup/<webtop_id>", methods=["DELETE"])
def cleanup_webtop(webtop_id):
    """
    Clean up webtop files and stop the container
    """
    try:
        webtop_dir = os.path.join(UPLOAD_DIR, f"webtop_{webtop_id}")

        if not os.path.exists(webtop_dir):
            return jsonify({
                "status": "error",
                "message": f"Webtop directory not found: {webtop_id}"
            }), 404

        # First, try to stop the container
        yaml_files = [f for f in os.listdir(webtop_dir) if f.endswith(('.yaml', '.yml'))]
        if yaml_files:
            yaml_path = os.path.join(webtop_dir, yaml_files[0])
            subprocess.run(
                ["docker", "compose", "-f", yaml_path, "down"],
                capture_output=True,
                text=True,
                cwd=webtop_dir
            )

        # Remove the directory and all its contents
        import shutil
        shutil.rmtree(webtop_dir)

        return jsonify({
            "status": "success",
            "message": f"Webtop cleaned up: {webtop_id}",
            "removed_directory": webtop_dir
        }), 200

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e),
            "webtop_id": webtop_id
        }), 500


@app.route("/deploy/list", methods=["GET"])
def list_webtops():
    """
    List all deployed webtops
    """
    try:
        webtops = []

        if not os.path.exists(UPLOAD_DIR):
            return jsonify({
                "status": "success",
                "webtops": [],
                "count": 0
            }), 200

        for dir_name in os.listdir(UPLOAD_DIR):
            if dir_name.startswith("webtop_"):
                webtop_id = dir_name.replace("webtop_", "")
                webtop_dir = os.path.join(UPLOAD_DIR, dir_name)

                # Check if container is running
                result = subprocess.run(
                    ["docker", "ps", "--filter", f"name=webtop-ubuntu-xfce-{webtop_id}", "--format", "{{.Names}}"],
                    capture_output=True,
                    text=True
                )

                is_running = bool(result.stdout.strip())

                webtops.append({
                    "webtop_id": webtop_id,
                    "directory": webtop_dir,
                    "is_running": is_running,
                    "container_name": f"webtop-ubuntu-xfce-{webtop_id}" if is_running else None
                })

        return jsonify({
            "status": "success",
            "webtops": webtops,
            "count": len(webtops)
        }), 200

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


# ============================================
# MAIN
# ============================================

if __name__ == "__main__":
    print("=" * 60)
    print("Webtop Backend API - Starting")
    print("=" * 60)
    print(f"Upload Directory: {UPLOAD_DIR}")
    print(f"Server URL: {SERVER_URL}")
    print(f"Listening on: http://0.0.0.0:5000")
    print("=" * 60)

    # Ensure upload directory exists
    os.makedirs(UPLOAD_DIR, exist_ok=True)

    # Run the app on all interfaces so other computers can connect
    app.run(host="0.0.0.0", port=5000, debug=True)
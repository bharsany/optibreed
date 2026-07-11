# Optibreed Windows Docker Installation Guide

This guide provides step-by-step instructions for installing and running the Optibreed application on a Windows operating system using Docker. Using Docker ensures that the application runs in an isolated, consistent environment.

## Prerequisites

Before starting the installation, ensure you have the following installed on your Windows machine:

1. **Windows Subsystem for Linux (WSL 2)**
   - WSL 2 provides better performance for Docker on Windows.
   - Open PowerShell as Administrator and run: `wsl --install`
   - Restart your computer if prompted.

2. **Docker Desktop for Windows**
   - Download the installer from the [official Docker website](https://docs.docker.com/desktop/install/windows-install/).
   - Run the installer and ensure the option to **"Use WSL 2 instead of Hyper-V"** is checked.
   - After installation, start Docker Desktop and ensure the Docker engine is running (the whale icon in the system tray should be green or the UI should say "Engine running").

3. **Git for Windows** (Optional but recommended)
   - To clone the repository, install Git from [git-scm.com](https://gitforwindows.org/).

---

## Step 1: Obtain the Application Code

You need to have the source code downloaded to your local Windows machine.

### Option A: Using Git (Recommended)
Open Command Prompt or PowerShell and run:
```cmd
git clone https://github.com/yourusername/optibreed.git
cd optibreed
```

### Option B: Download ZIP
1. Download the repository as a ZIP file from your version control platform (e.g., GitHub, GitLab).
2. Extract the ZIP file to a convenient folder (e.g., `C:\optibreed`).
3. Open Command Prompt or PowerShell and navigate to the extracted folder:
   ```cmd
   cd C:\optibreed
   ```

---

## Step 2: Build the Docker Image

The repository includes a [Dockerfile](file:///c:/Users/B%C3%A9la/Work/Parterv/Optibreed/optibreed/Dockerfile) that contains all the instructions needed to build the application environment.

1. Open PowerShell or Command Prompt.
2. Ensure you are in the application root directory (where the [Dockerfile](file:///c:/Users/B%C3%A9la/Work/Parterv/Optibreed/optibreed/Dockerfile) is located).
3. Build the Docker image by running the following command:

```cmd
docker build -t optibreed-app .
```

*Note: The `-t optibreed-app` flag tags the image with a readable name. Mind the period `.` at the end of the command—it tells Docker to use the current directory as the build context.*

Depending on your internet connection and system speed, this may take a few minutes as Docker downloads the base Python image and installs necessary dependencies (e.g., libcairo2-dev, pandas, flask).

---

## Step 3: Run the Docker Container

Once the image is built, you can run the application in a Docker container.

Run the following command to start the container:

```cmd
docker run -d -p 8080:8080 --name optibreed-container optibreed-app
```

**Understanding the command:**
- `-d`: Runs the container in detached mode (in the background).
- `-p 8080:8080`: Maps port 8080 on your host Windows machine to port 8080 inside the container.
- `--name optibreed-container`: Assigns a distinctive name to your running container.

*Note: If you need to set a different port, change the first number (e.g., `-p 80:8080` to access it on standard HTTP port).*

---

## Step 4: Verify the Installation

To verify that the application has been deployed successfully:

1. **Check Container Status**
   Run the following command to see if the container is running:
   ```cmd
   docker ps
   ```
   You should see `optibreed-container` listed with a status of "Up".

2. **Access the Application**
   Open your preferred web browser and navigate to:
   [http://localhost:8080](http://localhost:8080)
   
   You should see the Optibreed application loading correctly.

3. **Check the Health Endpoint**
   Navigate to [http://localhost:8080/health](http://localhost:8080/health) or the main dashboard to confirm the backend is responding correctly.

---

## Step 5: Managing the Application

Here are some useful commands for managing your Windows Docker deployment:

- **View application logs (useful for troubleshooting):**
  ```cmd
  docker logs -f optibreed-container
  ```

- **Stop the application:**
  ```cmd
  docker stop optibreed-container
  ```

- **Start the application again:**
  ```cmd
  docker start optibreed-container
  ```

- **Completely remove the container (if you need to rebuild/restart fresh):**
  ```cmd
  docker rm -f optibreed-container
  ```

---

## Troubleshooting Common Windows Issues

### 1. "Docker is not recognized as an internal or external command"
**Fix:** Docker Desktop is not running or not added to your Windows PATH. Start Docker Desktop from the Start Menu, wait for it to initialize, and restart your PowerShell terminal.

### 2. Port Allocation Error (Port 8080 is already in use)
**Fix:** Another application is using port 8080. You can run Optibreed on a different port by changing the mapping:
```cmd
docker run -d -p 8081:8080 --name optibreed-container optibreed-app
```
Then access the app at `http://localhost:8081`.

### 3. File Path Issues during Build
**Fix:** If you encounter issues related to line endings (CRLF vs LF) in shell scripts or configurations, ensure Git is configured to checkout files `as-is` or handle line endings properly. However, since we are doing everything inside the Docker Linux container, simply ensuring the Docker build runs successfully should mitigate this.

### 4. High Memory/CPU Usage
**Fix:** Docker Desktop allows you to limit resources.
Open Docker Desktop settings (Gear icon) -> Resources -> Advanced (or WSL integration settings depending on version). You can allocate specific amounts of RAM or CPU limits if the application uses too much memory for large pedigrees.

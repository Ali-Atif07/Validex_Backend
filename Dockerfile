# Use an official Python runtime as a parent image
FROM python:3.12-slim

# Set environment variables to prevent interactive prompts
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV TZ=Etc/UTC

# --- EFFICIENT INSTALLATION LAYER ---
# Combine all system dependency installations into a single RUN command
# This creates fewer layers and builds faster.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    # For Node.js installation
    curl \
    gnupg \
    # For Selenium/Scraping
    chromium \
    chromium-driver \
    tesseract-ocr \
    # For Node.js runtime (including npm)
    nodejs \
    npm \
    # Clean up apt cache to keep the image small
    && rm -rf /var/lib/apt/lists/*

# Set the working directory in the container
WORKDIR /app

# Copy dependency files first to leverage Docker's build cache
COPY requirements.txt package*.json ./

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Install Node.js dependencies
RUN npm install

# Copy the rest of your application code
COPY . .

# Expose the port your app runs on
EXPOSE 5000

# --- CORRECT START COMMAND ---
# Use index.js to start your Node.js application (assuming the entry point is index.js)
CMD ["node", "index.js"]

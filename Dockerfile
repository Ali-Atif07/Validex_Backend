FROM python:3.12-slim

# Install Node.js, Chromium, Tesseract
RUN apt-get update && apt-get install -y \
    curl gnupg \
    tesseract-ocr chromium chromium-driver \
    && curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Copy Node files and install dependencies
COPY package*.json ./
RUN npm install

# Copy rest of project
COPY . .

# Environment variables
ENV PYTHON_PATH=python3
ENV TESSDATA_PREFIX=/usr/share/tesseract-ocr/4.00/tessdata

EXPOSE 5000

CMD ["node", "index.js"]

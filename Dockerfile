FROM node:18

# Install Python and pip
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    tesseract-ocr \
    chromium \
    chromium-driver \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy package files
COPY package*.json ./
COPY requirements.txt ./

# Install Node.js dependencies
RUN npm install

# Install Python dependencies
RUN pip3 install -r requirements.txt

# Copy application code
COPY . .

# Set environment variables
ENV PYTHON_PATH=python3
ENV TESSDATA_PREFIX=/usr/share/tesseract-ocr/4.00/tessdata

EXPOSE 5000

CMD ["node", "index.js"]
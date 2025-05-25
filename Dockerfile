# Start from an official Python image
FROM python:3.11-slim

# Install curl and Node.js 18.x (includes npm and npx)
RUN apt-get update && apt-get install -y curl \
  && curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
  && apt-get install -y nodejs \
  && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy Python dependencies and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy Node.js dependencies and install (if you have package.json)
COPY package.json package-lock.json ./
RUN npm install

# Copy the rest of your app
COPY . .

# Expose the port your app will run on
EXPOSE 10000

# Run your app with uvicorn (adjust app module and port accordingly)
CMD ["uvicorn", "maps_agent:app", "--host", "0.0.0.0", "--port", "10000"]
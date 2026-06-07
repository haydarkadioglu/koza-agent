# Base image
FROM python:3.12-slim-bookworm

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/home/koza/.local/bin:${PATH}"

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    git \
    procps \
    tini \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user 'koza'
RUN groupadd -g 1000 koza && \
    useradd -u 1000 -g koza -m -s /bin/bash koza

# Set up directories
WORKDIR /app
RUN chown -R koza:koza /app

# Switch to non-root user
USER koza

# Pre-create config directory and notes so they have the correct owner
RUN mkdir -p /home/koza/.Koza /home/koza/notes

# Copy requirements and install dependencies
COPY --chown=koza:koza requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Copy application files
COPY --chown=koza:koza . .

# Install Koza package
RUN pip install --no-cache-dir --user -e .

# Expose multi-host sync port
EXPOSE 7420

# Persist configuration, database, and workspace
VOLUME ["/home/koza/.Koza", "/home/koza/notes"]

# Use tini as entrypoint
ENTRYPOINT ["tini", "-s", "--"]

# Run interactive chat by default
CMD ["koza", "start"]

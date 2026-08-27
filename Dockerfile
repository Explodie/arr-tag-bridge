FROM python:3.12-alpine

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bridge.py .

# Run as non-root
RUN adduser -D bridge && chown bridge:bridge /app
USER bridge

HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD curl -f http://localhost:5056/health || exit 1

EXPOSE 5056
CMD ["python", "bridge.py"]
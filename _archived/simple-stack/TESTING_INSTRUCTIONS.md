# Testing Instructions - Simplified MVP

## Quick Testing (5 minutes)

### 1. Basic Startup Test
```bash
cd /home/nicolas/Documents/delta4/valinor-saas

# Test direct startup
./start_simple.sh
```

Expected output:
```
🚀 Starting Valinor SaaS - Simple MVP
===============================================
📦 Checking dependencies...
✅ Setup complete
🌐 Starting server on http://localhost:8000
```

### 2. Health Check
In another terminal:
```bash
curl http://localhost:8000/health
```

Expected response:
```json
{"status": "healthy", "version": "simple-mvp"}
```

### 3. API Documentation
Open browser: http://localhost:8000/docs

Should show FastAPI interactive docs with 3 endpoints:
- GET /health
- POST /api/analyze  
- GET /api/status/{job_id}
- GET /api/results/{job_id}

### 4. Mock Analysis Test
```bash
curl -X POST http://localhost:8000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "client_name": "test_client",
    "period": "Q1-2025", 
    "ssh_host": "demo.example.com",
    "ssh_user": "testuser",
    "ssh_key_path": "/tmp/fake_key",
    "db_host": "localhost", 
    "db_port": 5432,
    "db_connection_string": "postgresql://test:test@localhost:5432/test"
  }'
```

Expected response:
```json
{"job_id": "abc-123-def", "status": "pending"}
```

### 5. Status Tracking
```bash
# Use job_id from previous response
curl http://localhost:8000/api/status/abc-123-def
```

Expected progression:
```json
{"job_id": "abc-123-def", "status": "running", "progress": 45, "message": "Running simulated analysis..."}
```

Wait 10 seconds, then:
```json
{"job_id": "abc-123-def", "status": "completed", "progress": 100, "message": "Analysis completed successfully"}
```

### 6. Results Retrieval
```bash
curl http://localhost:8000/api/results/abc-123-def
```

Expected response:
```json
{
  "client_name": "test_client",
  "period": "Q1-2025", 
  "execution_time_seconds": 3.0,
  "findings": {
    "revenue_analysis": {...},
    "customer_analysis": {...},
    "risk_analysis": {...}
  },
  "reports_generated": ["executive_summary.pdf", "detailed_analysis.xlsx"]
}
```

## Docker Testing (Alternative)

### 1. Docker Build Test
```bash
docker-compose -f docker-compose.simple.yml build
```

### 2. Docker Run Test  
```bash
docker-compose -f docker-compose.simple.yml up
```

### 3. Test via Docker
```bash
# Same curl commands as above, but against containerized service
curl http://localhost:8000/health
```

## Integration Testing (Optional)

### 1. With Real SSH Connection
If you have access to a test SSH server:

```bash
# Create test SSH key
ssh-keygen -t rsa -b 2048 -f /tmp/test_ssh_key -N ""

# Test real analysis (will fail at DB connection, which is expected)
curl -X POST http://localhost:8000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "client_name": "real_test",
    "period": "Q1-2025",
    "ssh_host": "your-real-ssh-host.com", 
    "ssh_user": "your-username",
    "ssh_key_path": "/tmp/test_ssh_key",
    "db_host": "internal-db-host",
    "db_port": 5432,
    "db_connection_string": "postgresql://user:pass@internal-db-host:5432/db"
  }'
```

Expected: Should fail at DB connection (which is OK - SSH tunnel would work)

## Performance Testing

### Memory Usage
```bash
# Start server
./start_simple.sh &

# Check memory usage  
ps aux | grep "python.*simple_api"
```

Expected: <50MB RSS memory usage

### Response Time
```bash
# Time health check
time curl http://localhost:8000/health
```

Expected: <100ms response time

### Concurrent Jobs
```bash
# Start multiple analyses simultaneously
for i in {1..5}; do
  curl -X POST http://localhost:8000/api/analyze \
    -H "Content-Type: application/json" \
    -d "{\"client_name\": \"client_$i\", \"period\": \"Q1-2025\", \"ssh_host\": \"demo.com\", \"ssh_user\": \"test\", \"ssh_key_path\": \"/tmp/key\", \"db_host\": \"localhost\", \"db_port\": 5432, \"db_connection_string\": \"postgresql://test@localhost/db\"}" &
done
```

Expected: All jobs should start and run concurrently via threading

## Troubleshooting

### Common Issues & Solutions

1. **Port 8000 already in use**
   ```bash
   # Kill existing process
   pkill -f "python.*simple_api"
   
   # Or change port in simple_api.py
   uvicorn.run(app, host="0.0.0.0", port=8001)
   ```

2. **Missing dependencies**
   ```bash
   pip install -r requirements_simple.txt
   ```

3. **Permission denied on SSH key**
   ```bash
   chmod 600 /path/to/ssh/key
   ```

4. **JSON storage directory missing**
   ```bash
   mkdir -p /tmp/valinor_jobs
   ```

5. **Anthropic API key missing**
   ```bash
   export ANTHROPIC_API_KEY=sk-ant-your-key-here
   ```

## Success Criteria

✅ **MVP is successful if**:
1. Server starts in <10 seconds
2. Health endpoint responds
3. Can submit analysis requests
4. Jobs run in background via threading
5. Can track job progress
6. Can retrieve results
7. Memory usage <50MB
8. API docs accessible
9. Error handling works (try invalid job_id)
10. Multiple concurrent jobs work

## Next Steps After Testing

Once basic testing passes:
1. **Deploy** to staging environment
2. **Test** with real SSH/DB credentials
3. **Integrate** real Valinor v0 core
4. **Validate** with sample customer data
5. **Iterate** based on feedback

The goal is to prove the core concept works before adding complexity back.

---

**Remember: This MVP prioritizes simplicity and reliability over features. If it works reliably, we can add complexity gradually based on real user needs.**
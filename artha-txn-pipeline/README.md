# AI Transaction Processing Pipeline

An asynchronous backend system for processing financial transaction CSV files using **FastAPI**, **PostgreSQL**, **Redis**, **Celery**, and **Docker**. The application cleans transaction data, detects anomalies, classifies uncategorized merchants using an LLM, and generates a structured spending summary.

---

## Features

- Upload transaction CSV files
- Asynchronous processing using Celery + Redis
- Data cleaning and normalization
- Duplicate transaction removal
- Statistical anomaly detection
- Merchant category classification using an LLM
- Spending summary generation
- Job status polling
- REST API with Swagger documentation
- Dockerized deployment with a single command

---

## Technology Stack

| Component | Technology |
|-----------|------------|
| API | FastAPI |
| Database | PostgreSQL |
| Queue | Celery |
| Broker | Redis |
| LLM | Gemini / Mock Provider |
| Containerization | Docker & Docker Compose |
| ORM | SQLAlchemy |
| Validation | Pydantic |

---

# Project Structure

```
artha-txn-pipeline/
│
├── app/
│   ├── api/
│   ├── core/
│   ├── models/
│   ├── services/
│   └── workers/
│
├── docker/
├── data/
├── transactions.csv
├── docker-compose.yml
├── requirements.txt
└── README.md
```

---

# Processing Pipeline

When a CSV file is uploaded, the following steps are executed asynchronously:

1. Upload CSV
2. Create Job record
3. Queue Celery task
4. Clean data
5. Detect anomalies
6. Classify merchants using LLM
7. Generate spending summary
8. Store processed data
9. Mark job as completed

---

# Data Cleaning

The pipeline performs:

- Converts mixed date formats to ISO-8601
- Removes currency symbols
- Converts status values to uppercase
- Fills missing categories with "Uncategorised"
- Removes duplicate transactions

---

# Anomaly Detection

Transactions are flagged when:

- Amount exceeds **3× account median**
- Currency is **USD** for domestic-only merchants such as:
  - Swiggy
  - Ola
  - IRCTC

---

# LLM Processing

The application performs:

- Batch merchant classification
- Merchant category caching
- Narrative summary generation
- Retry logic with exponential backoff
- Graceful handling of LLM failures

Supported Categories:

- Food
- Shopping
- Travel
- Transport
- Utilities
- Entertainment
- Cash Withdrawal
- Other

---

# API Endpoints

## Upload CSV

```
POST /jobs/upload
```

Uploads a CSV file and immediately returns a Job ID.

---

## Job Status

```
GET /jobs/{job_id}/status
```

Returns:

- Pending
- Processing
- Completed
- Failed

---

## Job Results

```
GET /jobs/{job_id}/results
```

Returns:

- Cleaned transactions
- Anomalies
- Category breakdown
- LLM narrative summary

---

## List Jobs

```
GET /jobs
```

Optional filter:

```
GET /jobs?status=completed
```

---

# Running the Project

## Clone Repository

```bash
git clone https://github.com/aarya0044/ai-transaction-processing-pipeline.git
cd ai-transaction-processing-pipeline
```

---

## Create Environment File

```bash
cp .env.example .env
```

(Already configured for mock LLM provider.)

---

## Start Application

```bash
docker compose up --build
```

The following services will start automatically:

- FastAPI
- PostgreSQL
- Redis
- Celery Worker

---

# Swagger Documentation

Open:

```
http://localhost:8000/docs
```

---

# Example cURL Requests

## Upload CSV

```bash
curl -X POST http://localhost:8000/jobs/upload \
-F "file=@transactions.csv"
```

---

## Check Job Status

```bash
curl http://localhost:8000/jobs/<JOB_ID>/status
```

---

## Get Results

```bash
curl http://localhost:8000/jobs/<JOB_ID>/results
```

---

## List Jobs

```bash
curl http://localhost:8000/jobs
```

---

# Architecture

```
                Client
                   │
                   ▼
           FastAPI REST API
                   │
        Create Job + Save CSV
                   │
                   ▼
             Redis Queue
                   │
                   ▼
             Celery Worker
                   │
     ┌─────────────┼─────────────┐
     │             │             │
Cleaning     Anomaly Detection   LLM
     │             │             │
     └─────────────┼─────────────┘
                   │
                   ▼
            PostgreSQL Database
                   │
                   ▼
        Status & Results Endpoints
```

---

# Database

## Job

Stores:

- filename
- status
- progress
- timestamps
- errors

---

## Transaction

Stores:

- cleaned transaction
- anomaly information
- LLM classification

---

## Job Summary

Stores:

- total spend
- top merchants
- risk level
- narrative
- category breakdown

---

# Design Decisions

- Asynchronous processing prevents API blocking.
- Redis is used as the Celery broker.
- Merchant classifications are cached to reduce repeated LLM calls.
- Batch LLM requests improve performance.
- Processing failures do not stop the overall job.

---

# Improvements for Production

- Store uploaded files in AWS S3
- Horizontal worker scaling
- Multiple Celery queues
- JWT Authentication
- Rate limiting
- Monitoring with Prometheus & Grafana
- Kubernetes deployment
- CI/CD using GitHub Actions

---

# Author

**Aarya**

Backend + DevOps Internship Assignment

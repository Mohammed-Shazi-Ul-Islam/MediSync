# 🩺 MediSync

### AI-Powered Intelligent Patient Triage & Specialist Routing System

<p align="center">
  <strong>Developed by MOHAMMED SHAZI UL ISLAM</strong>
</p>

<p align="center">
  Intelligent • Scalable • Secure • AI-Driven Healthcare Backend
</p>

---

## 📖 About the Project

**MediSync** is a production-oriented backend platform that leverages Artificial Intelligence to streamline patient triage and specialist routing. The system analyzes patient-reported symptoms, determines the urgency of medical attention, and recommends the most appropriate medical specialist for further evaluation.

Designed with asynchronous processing and modern backend technologies, MediSync focuses on building a fast, scalable, and secure healthcare workflow capable of handling real-world clinical scenarios.

---

## ✨ Features

### 📝 Patient Intake

* Secure patient registration and authentication
* Symptom submission APIs
* Input validation
* Asynchronous request processing

### 🤖 AI Clinical Triage

* AI-powered symptom analysis
* Clinical insight generation
* Urgency classification

  * 🔴 Critical
  * 🟡 Moderate
  * 🟢 Routine
* Intelligent specialist recommendation

### 🏥 Specialist Routing

* Routes patients to the appropriate medical department
* Configurable specialty mapping
* Supports multiple clinical specialties

### 👨‍⚕️ Doctor Dashboard APIs

* Case review endpoints
* Accept or reject consultations
* Escalate urgent cases
* Workflow analytics

### 📨 Notification Pipeline

* Email notifications
* SMS notifications
* Background processing
* Retry mechanism
* Audit logging

### 🔐 Authentication & Security

* JWT Authentication
* Access & Refresh Tokens
* Role-Based Access Control (RBAC)
* Secure REST APIs
* Activity auditing

---

## 🏗️ System Architecture

```
Patient
    │
    ▼
Patient Intake API
    │
    ▼
AI Triage Engine
    │
    ▼
Specialist Router
    │
    ├──────────────► Notification Pipeline
    │                    │
    │                    ▼
    │               Doctor Alerts
    │
    ▼
Doctor Dashboard APIs
```

---

## 🛠️ Tech Stack

| Category               | Technologies            |
| ---------------------- | ----------------------- |
| **Backend**            | FastAPI                 |
| **Database**           | PostgreSQL              |
| **ORM**                | SQLAlchemy              |
| **Database Migration** | Alembic                 |
| **Background Tasks**   | Celery + Redis          |
| **AI Engine**          | Google Gemini           |
| **Vector Database**    | ChromaDB                |
| **Containerization**   | Docker & Docker Compose |

---

## 🎯 Project Objectives

* Build a scalable healthcare backend architecture
* Automate patient triage using AI
* Reduce specialist allocation time
* Improve clinical workflow efficiency
* Demonstrate production-ready backend engineering practices

---

## 📂 Core Modules

* 📝 Intake API
* 🤖 AI Triage Engine
* 🏥 Specialist Router
* 📨 Notification Pipeline
* 👨‍⚕️ Doctor Dashboard API
* 🔐 Authentication & Audit Layer

---

## 🚀 Current Status

> **Active Development**

The project is actively being enhanced with new features, performance improvements, and production-ready optimizations.

---

## 👨‍💻 Author

**MOHAMMED SHAZI UL ISLAM**


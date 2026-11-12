# Redis JWT AI Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace in-process seed/token state with Redis-backed runtime state, JWT access tokens with expiration, and a basic report-analysis path through `AIService`.

**Architecture:** `Store` owns Redis persistence for users and workspace data. Auth signs JWTs via `app.core.security`, while request dependencies decode JWTs and load users from Redis. Report section updates can request AI-generated analysis text through the existing chat-completion client.

**Tech Stack:** FastAPI, Redis, python-jose, passlib/bcrypt, pytest.

---

### Task 1: JWT Auth

**Files:**
- Modify: `app/core/config.py`
- Modify: `app/core/security.py`
- Modify: `app/api/deps.py`
- Modify: `app/services/store.py`
- Test: `tests/test_auth_jwt.py`

- [ ] Write tests that login returns a JWT containing `sub` and `exp`, `/auth/me` accepts it, and invalid tokens return 401.
- [ ] Run `pytest tests/test_auth_jwt.py -q` and confirm it fails before implementation.
- [ ] Add auth settings, JWT decode helper, and move token issuance out of `Store._tokens`.
- [ ] Run `pytest tests/test_auth_jwt.py -q` and confirm it passes.

### Task 2: Redis Store

**Files:**
- Modify: `app/services/store.py`
- Modify: `app/api/deps.py`
- Modify: `tests/test_seed_store.py`

- [ ] Write or update tests so `Store` reads and writes workspace state through Redis, including created accounts/tasks/materials/report updates.
- [ ] Run the focused Redis store test and confirm it fails before implementation.
- [ ] Serialize dataclasses to JSON under Redis keys for users and workspace data.
- [ ] Run the focused Redis store test and confirm it passes against configured Redis.

### Task 3: AI Report Analysis

**Files:**
- Modify: `app/services/ai_service.py`
- Modify: `app/api/routes/reports.py`
- Modify: `app/schemas/reports.py`
- Test: `tests/test_ai_report_analysis.py`

- [ ] Write tests that an analyze request calls an injected AI service and stores the generated report section in Redis.
- [ ] Run the AI report test and confirm it fails before implementation.
- [ ] Add an async `analyze_report_section` helper and an endpoint that stores its result through `Store`.
- [ ] Run the AI report test and confirm it passes.

### Task 4: Cleanup And Verification

**Files:**
- Modify: `requirements.txt`
- Modify: `pyproject.toml`
- Modify: `README.md`

- [ ] Add missing JWT/password dependencies.
- [ ] Remove runtime dependency on `app/services/seed.py`.
- [ ] Run `pytest tests -q`.

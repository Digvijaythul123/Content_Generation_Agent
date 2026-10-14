# System Architecture

## Components
- Manager Agent
- Content Agent
- Approval Agent
- Publishing Agent
- Analytics Agent

## Flow
User -> Manager Agent -> Content Agent -> Database -> Approval Agent -> Publishing Agent -> Instagram -> Analytics Agent

## Data Store
SQLite for MVP, PostgreSQL later.

## Integrations
OpenAI/Claude, Instagram Graph API.
